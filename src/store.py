import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(con: sqlite3.Connection, table_name: str):
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}


def _parse_timestamp(value: str):
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)

def init_db(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_items (
            item_id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            last_alerted TEXT,
            alert_count INTEGER NOT NULL DEFAULT 0
        );
    """)
    columns = _table_columns(con, "seen_items")
    if "last_alerted" not in columns:
        cur.execute("ALTER TABLE seen_items ADD COLUMN last_alerted TEXT")
    if "alert_count" not in columns:
        cur.execute("ALTER TABLE seen_items ADD COLUMN alert_count INTEGER NOT NULL DEFAULT 0")
    con.commit()
    return con

def touch_item(con: sqlite3.Connection, item_id: str):
    now = _utc_now()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO seen_items (item_id, first_seen, last_seen, alert_count)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(item_id) DO UPDATE SET
            last_seen = excluded.last_seen
        """,
        (item_id, now, now),
    )
    con.commit()


def should_alert(con: sqlite3.Connection, item_id: str, min_hours_between_alerts: float) -> bool:
    cur = con.cursor()
    cur.execute("SELECT last_alerted FROM seen_items WHERE item_id = ?", (item_id,))
    row = cur.fetchone()
    if row is None or row[0] is None:
        return True

    if min_hours_between_alerts <= 0:
        return True

    last_alerted = _parse_timestamp(row[0])
    return datetime.now(timezone.utc) >= last_alerted + timedelta(hours=min_hours_between_alerts)


def mark_alerted(con: sqlite3.Connection, item_id: str):
    now = _utc_now()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO seen_items (item_id, first_seen, last_seen, last_alerted, alert_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(item_id) DO UPDATE SET
            last_seen = excluded.last_seen,
            last_alerted = excluded.last_alerted,
            alert_count = COALESCE(seen_items.alert_count, 0) + 1
        """,
        (item_id, now, now, now),
    )
    con.commit()
