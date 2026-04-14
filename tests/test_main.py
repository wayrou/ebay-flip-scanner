import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import main


class FakeOAuth:
    def get_app_token(self):
        return "token"


def fake_browse_search(**kwargs):
    return {
        "itemSummaries": [
            {
                "itemId": "item-123",
                "title": "RTX 3080 10GB boots in Windows but crashes under load",
                "price": {"value": "80"},
                "shippingOptions": [{"shippingCost": {"value": "15"}}],
                "itemWebUrl": "https://example.com/item-123",
                "seller": {"feedbackPercentage": "99.8", "feedbackScore": "1500"},
                "shortDescription": "Shows display output and then fails Furmark.",
            }
        ]
    }


class MainTests(unittest.TestCase):
    def test_config_exposes_multiple_markets(self):
        config = main.load_config()
        enabled_markets = main.get_enabled_markets(config)
        self.assertGreaterEqual(len(enabled_markets), 5)
        self.assertEqual(enabled_markets[0]["key"], "gpu")

    def test_negative_expected_profit_never_alerts(self):
        row = {
            "bucket": "GREEN",
            "score": 80,
            "expected_profit": -45.0,
        }
        self.assertFalse(main.listing_qualifies(row, min_score_alert=65, min_expected_profit=25))

    def test_missing_expected_profit_never_alerts(self):
        row = {
            "bucket": "GREEN",
            "score": 80,
            "expected_profit": None,
        }
        self.assertFalse(main.listing_qualifies(row, min_score_alert=65, min_expected_profit=25))

    def test_alert_skip_reason_reports_negative_profit(self):
        row = {
            "bucket": "GREEN",
            "score": 80,
            "expected_profit": -44.81,
            "min_score_alert": 65,
            "min_expected_profit": 25,
        }
        self.assertIn("below threshold", main.alert_skip_reason(row))

    def test_load_local_env_prefers_secrets_env_before_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            secrets_path = Path(tmpdir) / "secrets.env"
            dotenv_path = Path(tmpdir) / ".env"

            secrets_path.write_text(
                "DISCORD_WEBHOOK_URL=https://discord.test/first\nEBAY_CLIENT_ID=client-id\n",
                encoding="utf-8",
            )
            dotenv_path.write_text(
                "DISCORD_WEBHOOK_URL=https://discord.test/second\nEBAY_CLIENT_SECRET=client-secret\n",
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                loaded = main.load_local_env([secrets_path, dotenv_path])
                self.assertEqual([path.name for path in loaded], ["secrets.env", ".env"])
                self.assertEqual(os.environ["DISCORD_WEBHOOK_URL"], "https://discord.test/first")
                self.assertEqual(os.environ["EBAY_CLIENT_ID"], "client-id")
                self.assertEqual(os.environ["EBAY_CLIENT_SECRET"], "client-secret")

    def test_duplicate_item_results_only_alert_once_until_cooldown_expires(self):
        cfg = main.load_config()
        cfg.setdefault("runtime", {})

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg["db"] = {"path": str(Path(tmpdir) / "scanner.sqlite")}
            cfg["runtime"]["min_hours_between_alerts"] = 24
            messages = []

            with mock.patch.dict(
                "os.environ",
                {"DISCORD_WEBHOOK_URL": "https://discord.test/webhook"},
                clear=False,
            ):
                with mock.patch.object(main, "browse_search", side_effect=fake_browse_search):
                    with mock.patch.object(
                        main,
                        "discord_alert",
                        side_effect=lambda webhook, content: messages.append(content),
                    ):
                        main.scan_once(cfg, FakeOAuth())
                        main.scan_once(cfg, FakeOAuth())
                        self.assertEqual(len(messages), 1)

                        cfg["runtime"]["min_hours_between_alerts"] = 0
                        main.scan_once(cfg, FakeOAuth())
                        self.assertEqual(len(messages), 2)

    def test_run_forever_can_be_stopped_by_event(self):
        stop_event = threading.Event()
        statuses = []

        with mock.patch.object(main, "prepare_runtime", return_value=FakeOAuth()):
            with mock.patch.object(main, "load_config", return_value={"runtime": {"scan_interval_minutes": 15}}):
                with mock.patch.object(
                    main,
                    "scan_once",
                    side_effect=lambda cfg, oauth: stop_event.set(),
                ):
                    main.run_forever(stop_event=stop_event, on_status=statuses.append)

        self.assertIn("Scanning eBay", statuses)
        self.assertEqual(statuses[-1], "Stopped")


if __name__ == "__main__":
    unittest.main()
