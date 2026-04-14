import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from store import init_db, mark_alerted, should_alert, touch_item


class StoreTests(unittest.TestCase):
    def test_existing_database_is_migrated_and_alerts_are_tracked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "scanner.sqlite"

            con = sqlite3.connect(db_path)
            con.execute(
                """
                CREATE TABLE seen_items (
                    item_id TEXT PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )
            con.execute(
                "INSERT INTO seen_items (item_id, first_seen, last_seen) VALUES (?, ?, ?)",
                ("item-1", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )
            con.commit()
            con.close()

            con = init_db(str(db_path))
            self.assertTrue(should_alert(con, "item-1", 24))

            touch_item(con, "item-1")
            mark_alerted(con, "item-1")

            self.assertFalse(should_alert(con, "item-1", 24))
            self.assertTrue(should_alert(con, "item-1", 0))

            row = con.execute(
                "SELECT alert_count, last_alerted FROM seen_items WHERE item_id = ?",
                ("item-1",),
            ).fetchone()
            self.assertEqual(row[0], 1)
            self.assertIsNotNone(row[1])
            con.close()


if __name__ == "__main__":
    unittest.main()
