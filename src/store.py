import sqlite3
from pathlib import Path
from datetime import datetime

def init_db(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_items (
            item_id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
    """)
    con.commit()
    return con

def mark_seen(con: sqlite3.Connection, item_id: str):
    now = datetime.utcnow().isoformat()
    cur = con.cursor()
    cur.execute("SELECT item_id FROM seen_items WHERE item_id = ?", (item_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("UPDATE seen_items SET last_seen = ? WHERE item_id = ?", (now, item_id))
    else:
        cur.execute("INSERT INTO seen_items (item_id, first_seen, last_seen) VALUES (?, ?, ?)", (item_id, now, now))
    con.commit()

def is_seen(con: sqlite3.Connection, item_id: str) -> bool:
    cur = con.cursor()
    cur.execute("SELECT item_id FROM seen_items WHERE item_id = ?", (item_id,))
    return cur.fetchone() is not None