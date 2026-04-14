import csv
import logging
import os
import re
import time
from pathlib import Path
from threading import Event
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import yaml

from alerts import discord_alert
from ebay_browse import browse_search
from ebay_oauth import EbayOAuth
from estimator import expected_profit
from market_profiles import MARKET_PROFILES, get_market_profile
from rules import classify
from scoring import score_listing
from store import init_db, mark_alerted, should_alert, touch_item


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DEFAULT_GPU_COMPS_PATH = BASE_DIR / "data" / "comps" / "gpus.csv"
LEGACY_GPU_COMPS_PATH = BASE_DIR / "comps.csv"
ENV_PATHS = (BASE_DIR / "secrets.env", BASE_DIR / ".env")
LOGGER = logging.getLogger("ebay_flip_scanner")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def load_local_env(paths: Iterable[Path] = ENV_PATHS) -> List[Path]:
    loaded_paths: List[Path] = []

    for path in paths:
        if not path.exists():
            continue

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key.startswith("export "):
                key = key[len("export ") :].strip()

            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]

            os.environ.setdefault(key, value)

        loaded_paths.append(path)

    return loaded_paths


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _emit_status(on_status: Optional[Callable[[str], None]], message: str) -> None:
    if on_status is not None:
        on_status(message)


def prepare_runtime() -> EbayOAuth:
    loaded_paths = load_local_env()
    if loaded_paths:
        LOGGER.info("Loaded secrets from %s", ", ".join(path.name for path in loaded_paths))
    else:
        LOGGER.warning("No env file found. Expected one of: %s", ", ".join(path.name for path in ENV_PATHS))

    require_env("DISCORD_WEBHOOK_URL")
    require_env("EBAY_CLIENT_ID")
    require_env("EBAY_CLIENT_SECRET")
    return EbayOAuth()


def _merge_settings(base: Optional[Dict[str, Any]], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(base or {})
    merged.update(override or {})
    return merged


def _normalize_legacy_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    if "markets" in raw_config:
        return raw_config

    return {
        "defaults": {},
        "markets": [
            {
                "key": "gpu",
                "display_name": "GPUs",
                "comps_path": str(LEGACY_GPU_COMPS_PATH),
                "search": raw_config.get("search", {}),
                "thresholds": raw_config.get("thresholds", {}),
                "assumptions": raw_config.get("assumptions", {}),
            }
        ],
        "db": raw_config.get("db", {}),
        "runtime": raw_config.get("runtime", {}),
    }


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}
    return _normalize_legacy_config(raw_config)


def get_enabled_markets(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    defaults = config.get("defaults", {})
    markets: List[Dict[str, Any]] = []

    for market in config.get("markets", []):
        if market.get("enabled", True) is False:
            continue

        market_key = market.get("key", "").strip()
        if not market_key:
            continue

        profile = get_market_profile(market_key)
        normalized_market = dict(market)
        normalized_market["display_name"] = market.get("display_name", profile.display_name)
        normalized_market["search"] = _merge_settings(defaults.get("search"), market.get("search"))
        normalized_market["thresholds"] = _merge_settings(defaults.get("thresholds"), market.get("thresholds"))
        normalized_market["assumptions"] = _merge_settings(defaults.get("assumptions"), market.get("assumptions"))

        if "comps_path" not in normalized_market:
            normalized_market["comps_path"] = str(DEFAULT_GPU_COMPS_PATH) if market_key == "gpu" else ""

        markets.append(normalized_market)

    return markets


def load_comps(path: Path = DEFAULT_GPU_COMPS_PATH) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("model"):
                continue
            rows.append(
                {
                    "model": str(row["model"]),
                    "working": float(row["working_resale"]),
                    "asis": float(row["as_is_resale"]),
                }
            )
    return rows


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def estimate_comps(
    title: str, comps_rows: List[Dict[str, Any]]
) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    normalized_title = normalize_title(title)
    best_match = None
    best_length = 0

    for row in comps_rows:
        key = normalize_title(row["model"])
        if key and key in normalized_title and len(key) > best_length:
            best_match = row
            best_length = len(key)

    if not best_match:
        return None, None, None

    return (
        best_match["model"],
        float(best_match["working"]),
        float(best_match["asis"]),
    )


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_currency(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"${value:.2f}"


def log_safe_text(value: Any) -> str:
    return str(value).encode("ascii", errors="replace").decode("ascii")


def build_alert_message(row: Dict[str, Any]) -> str:
    query_list = ", ".join(row.get("queries") or [row.get("query", "n/a")])
    return "\n".join(
        [
            "[Resale Candidate]",
            f"Market: {row['market_display_name']} | Bucket: {row['bucket']} | Score: {row['score']} | Expected profit: {format_currency(row['expected_profit'])}",
            f"Price + Ship: {format_currency(row['price'])} + {format_currency(row['ship'])}",
            f"Model match: {row['model_match'] or 'n/a'}",
            f"Search queries: {query_list}",
            row["title"],
            row["url"],
            f"Why: {row['why']}",
        ]
    )


def alert_skip_reason(row: Dict[str, Any]) -> Optional[str]:
    min_score_alert = int(row["min_score_alert"])
    min_expected_profit = float(row["min_expected_profit"])

    if row["bucket"] not in ("GREEN", "YELLOW"):
        return f"bucket {row['bucket']} is not alertable"

    if int(row["score"]) < min_score_alert:
        return f"score {row['score']} below threshold {min_score_alert}"

    exp_val = row["expected_profit"]
    if exp_val is None:
        return "expected profit unavailable"

    if float(exp_val) < min_expected_profit:
        return f"expected profit {format_currency(exp_val)} below threshold {format_currency(min_expected_profit)}"

    return None


def log_top_results(rows: List[Dict[str, Any]], max_results: int, heading: str) -> None:
    if not rows:
        LOGGER.info("No listings returned for %s in this scan.", heading)
        return

    LOGGER.info("Top %s listings for %s:", min(max_results, len(rows)), heading)
    for row in rows[:max_results]:
        skip_reason = alert_skip_reason(row)
        alert_status = "alert-ready" if skip_reason is None else f"skipped: {skip_reason}"
        LOGGER.info(
            "[%s] score=%s exp=%s buy=%s ship=%s model=%s | %s | %s | %s",
            row["bucket"],
            row["score"],
            format_currency(row["expected_profit"]),
            format_currency(row["price"]),
            format_currency(row["ship"]),
            log_safe_text(row["model_match"] or "n/a"),
            log_safe_text(row["title"]),
            log_safe_text(row["why"]),
            log_safe_text(alert_status),
        )


def listing_qualifies(row: Dict[str, Any], min_score_alert: int, min_expected_profit: float) -> bool:
    return (
        alert_skip_reason(
            {
                **row,
                "min_score_alert": min_score_alert,
                "min_expected_profit": min_expected_profit,
            }
        )
        is None
    )


def row_rank(row: Dict[str, Any]) -> Tuple[int, int, float]:
    bucket_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    expected_profit_rank = row["expected_profit"] if row["expected_profit"] is not None else float("-inf")
    return (
        bucket_order.get(row["bucket"], 9),
        -int(row["score"]),
        -expected_profit_rank,
    )


def _merge_candidate(
    rows_by_item: Dict[str, Dict[str, Any]],
    candidate: Dict[str, Any],
) -> None:
    item_id = str(candidate["item_id"])
    existing = rows_by_item.get(item_id)
    if existing is None:
        rows_by_item[item_id] = candidate
        return

    existing_queries = existing.setdefault("queries", [])
    for query in candidate.get("queries", []):
        if query not in existing_queries:
            existing_queries.append(query)

    if row_rank(candidate) < row_rank(existing):
        candidate["queries"] = existing_queries
        rows_by_item[item_id] = candidate
    else:
        existing["query"] = existing_queries[0]


def scan_market(
    market_config: Dict[str, Any],
    token: str,
    marketplace: str,
) -> List[Dict[str, Any]]:
    market_key = market_config["key"]
    profile = get_market_profile(market_key)
    search_cfg = market_config.get("search", {})
    threshold_cfg = market_config.get("thresholds", {})
    assumption_cfg = market_config.get("assumptions", {})

    max_price = safe_float(threshold_cfg.get("max_price"), 400.0)
    min_score_alert = safe_int(threshold_cfg.get("min_score_alert"))
    if min_score_alert is None:
        min_score_alert = 60

    min_expected_profit = safe_float(threshold_cfg.get("min_expected_profit"), 25.0)
    max_results_print = safe_int(threshold_cfg.get("max_results_print"))
    if max_results_print is None or max_results_print <= 0:
        max_results_print = 10

    search_limit = safe_int(search_cfg.get("limit_per_query"))
    if search_limit is None or search_limit <= 0:
        search_limit = 50

    queries = search_cfg.get("queries") or []
    if not queries:
        LOGGER.warning("No search queries configured for market %s.", market_config["display_name"])
        return []

    comps_path_value = str(market_config.get("comps_path", "")).strip()
    comps_rows: List[Dict[str, Any]] = []
    if comps_path_value:
        comps_path = resolve_project_path(comps_path_value)
        if comps_path.exists():
            comps_rows = load_comps(comps_path)
        else:
            LOGGER.warning("Comps file for %s was not found: %s", market_config["display_name"], comps_path)

    buying_options = search_cfg.get("buying_options") or []
    rows_by_item: Dict[str, Dict[str, Any]] = {}

    for query in queries:
        try:
            data = browse_search(
                token=token,
                q=query,
                limit=search_limit,
                marketplace_id=marketplace,
                buying_options=buying_options,
                category_ids=search_cfg.get("category_ids"),
            )
        except Exception:
            LOGGER.exception("Search failed for market %s query: %s", market_config["display_name"], query)
            continue

        for item in data.get("itemSummaries", []):
            item_id = item.get("itemId") or item.get("legacyItemId") or ""
            if not item_id:
                continue

            title = item.get("title", "")
            price = safe_float((item.get("price") or {}).get("value"))
            if price is None or price <= 0 or price > max_price:
                continue

            ship = safe_float(assumption_cfg.get("shipping_cost_default"), 18.0)
            shipping_options = item.get("shippingOptions") or []
            if shipping_options:
                shipping_cost = (shipping_options[0] or {}).get("shippingCost", {}) or {}
                if shipping_cost.get("value") is not None:
                    ship = safe_float(shipping_cost.get("value"), ship)

            item_url = item.get("itemWebUrl", "")
            seller = item.get("seller", {}) or {}
            feedback_pct = safe_float(seller.get("feedbackPercentage"), default=None)
            feedback_score = safe_int(seller.get("feedbackScore"))

            short_desc = item.get("shortDescription", "") or ""
            text_blob = f"{title}\n{short_desc}"

            bucket, _ = classify(text_blob, profile_key=market_key)
            matched_model, est_working, est_as_is = estimate_comps(title, comps_rows)
            score, why_list = score_listing(
                text_blob,
                feedback_pct,
                feedback_score,
                price,
                est_working,
                profile_key=market_key,
            )

            if bucket == "GREEN":
                p_fix = safe_float(assumption_cfg.get("p_fix_green"), 0.65)
            elif bucket == "YELLOW":
                p_fix = safe_float(assumption_cfg.get("p_fix_yellow"), 0.35)
            else:
                p_fix = safe_float(assumption_cfg.get("p_fix_red"), 0.10)

            exp_profit: Optional[float] = None
            if est_working is not None and est_as_is is not None:
                exp_profit = expected_profit(
                    buy=price,
                    ship=ship,
                    est_working=est_working,
                    est_as_is=est_as_is,
                    p_fix=p_fix,
                    fee_rate=safe_float(assumption_cfg.get("ebay_fee_rate"), 0.135),
                    parts_cost=safe_float(assumption_cfg.get("parts_cost_default"), 18.0),
                    time_cost=safe_float(assumption_cfg.get("time_cost_default"), 30.0),
                )

            candidate = {
                "query": query,
                "queries": [query],
                "market_key": market_key,
                "market_display_name": market_config["display_name"],
                "bucket": bucket,
                "score": score,
                "expected_profit": exp_profit,
                "price": price,
                "ship": ship,
                "model_match": matched_model,
                "title": title,
                "url": item_url,
                "why": "; ".join(why_list),
                "item_id": item_id,
                "min_score_alert": min_score_alert,
                "min_expected_profit": min_expected_profit,
            }
            _merge_candidate(rows_by_item, candidate)

    rows = sorted(rows_by_item.values(), key=row_rank)
    log_top_results(rows, max_results_print, market_config["display_name"])
    return rows


def scan_once(config: Dict[str, Any], oauth: EbayOAuth) -> None:
    markets = get_enabled_markets(config)
    if not markets:
        LOGGER.warning("No enabled markets found in %s.", CONFIG_PATH)
        return

    db_cfg = config.get("db", {})
    runtime_cfg = config.get("runtime", {})
    min_hours_between_alerts = safe_float(runtime_cfg.get("min_hours_between_alerts"), 24.0)
    db_path = resolve_project_path(str(db_cfg.get("path", "scanner.sqlite")))

    webhook = require_env("DISCORD_WEBHOOK_URL")
    marketplace = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    con = init_db(str(db_path))

    try:
        token = oauth.get_app_token()
        rows_by_item: Dict[str, Dict[str, Any]] = {}

        for market_config in markets:
            for row in scan_market(market_config, token, marketplace):
                _merge_candidate(rows_by_item, row)

        rows = sorted(rows_by_item.values(), key=row_rank)
        alerts_sent = 0
        for row in rows:
            item_id = str(row["item_id"])
            touch_item(con, item_id)

            if not listing_qualifies(
                row,
                min_score_alert=int(row["min_score_alert"]),
                min_expected_profit=float(row["min_expected_profit"]),
            ):
                continue

            if not should_alert(con, item_id, float(min_hours_between_alerts)):
                continue

            try:
                discord_alert(webhook, build_alert_message(row))
            except Exception:
                LOGGER.exception("Discord delivery failed for item %s.", item_id)
                continue

            mark_alerted(con, item_id)
            alerts_sent += 1

        LOGGER.info(
            "Scan finished. %s listings evaluated across %s markets, %s Discord alerts sent.",
            len(rows),
            len(markets),
            alerts_sent,
        )
    finally:
        con.close()


def run_forever(
    stop_event: Optional[Event] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> None:
    oauth = prepare_runtime()
    LOGGER.info("Scanner starting from %s", BASE_DIR)
    _emit_status(on_status, "Running")

    while not (stop_event and stop_event.is_set()):
        scan_interval_minutes = 15.0
        cycle_started_at = time.monotonic()
        try:
            config = load_config(CONFIG_PATH)
            runtime_cfg = config.get("runtime", {})
            scan_interval_minutes = safe_float(runtime_cfg.get("scan_interval_minutes"), 15.0)
            if scan_interval_minutes is None or scan_interval_minutes <= 0:
                LOGGER.warning("Invalid scan interval in config. Falling back to 15 minutes.")
                scan_interval_minutes = 15.0

            _emit_status(on_status, "Scanning eBay")
            scan_once(config, oauth)
        except KeyboardInterrupt:
            LOGGER.info("Scanner stopped by user.")
            _emit_status(on_status, "Stopped")
            raise
        except Exception:
            LOGGER.exception("Scan cycle failed.")
            _emit_status(on_status, "Error, retrying")

        elapsed_seconds = time.monotonic() - cycle_started_at
        sleep_seconds = max(5.0, (scan_interval_minutes * 60.0) - elapsed_seconds)
        LOGGER.info("Sleeping for %.1f minutes before the next scan.", sleep_seconds / 60.0)
        _emit_status(on_status, f"Sleeping for {sleep_seconds / 60.0:.1f} minutes")
        if stop_event:
            stop_event.wait(timeout=sleep_seconds)
        else:
            time.sleep(sleep_seconds)

    LOGGER.info("Scanner loop stopped.")
    _emit_status(on_status, "Stopped")


def main() -> None:
    configure_logging()
    try:
        run_forever()
    except KeyboardInterrupt:
        LOGGER.info("Scanner stopped.")
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
