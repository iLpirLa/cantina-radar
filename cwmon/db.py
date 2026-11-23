from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    id              INTEGER PRIMARY KEY,
    title           TEXT,
    slug            TEXT,
    category_id     INTEGER,
    image_url       TEXT,
    producer        TEXT,
    cuvee           TEXT,
    appellation     TEXT,
    vintage         INTEGER,
    nv              INTEGER DEFAULT 0,
    mixed           INTEGER DEFAULT 0,
    bottles         INTEGER,
    bottle_eq       REAL,
    size_l          REAL,
    wine_name       TEXT,
    wine_key        TEXT,
    parse_ok        INTEGER DEFAULT 0,
    first_seen      INTEGER,
    last_seen       INTEGER,
    end_time        INTEGER,
    current_bid     REAL,
    currency        TEXT DEFAULT 'EUR',
    reserve_set     INTEGER,
    reserve_met     INTEGER,
    close_status    TEXT,
    final           INTEGER DEFAULT 0,
    sold            INTEGER,
    estimate_low    REAL,
    estimate_high   REAL,
    estimate_checked INTEGER DEFAULT 0,
    -- ultimo calcolo di valutazione (per dashboard/bot)
    market_per_bottle REAL,
    cost_per_bottle   REAL,
    discount          REAL,
    confidence        REAL,
    value_source      TEXT,
    max_bid           REAL,
    scored_at         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_lots_key ON lots(wine_key, vintage);
CREATE INDEX IF NOT EXISTS idx_lots_end ON lots(end_time);
CREATE INDEX IF NOT EXISTS idx_lots_final ON lots(final);

CREATE TABLE IF NOT EXISTS alerts (
    lot_id   INTEGER,
    kind     TEXT,
    sent_at  INTEGER,
    discount REAL,
    PRIMARY KEY (lot_id, kind)
);

CREATE TABLE IF NOT EXISTS vivino (
    wine_key     TEXT,
    vintage      INTEGER,
    query        TEXT,
    name         TEXT,
    year         INTEGER,
    rating       REAL,
    rating_count INTEGER,
    price        REAL,
    currency     TEXT,
    url          TEXT,
    fetched_at   INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vivino ON vivino(wine_key, COALESCE(vintage, 0));

CREATE TABLE IF NOT EXISTS manual_values (
    wine_key   TEXT,
    vintage    INTEGER,          -- NULL = vale per tutte le annate
    wine_name  TEXT,
    name       TEXT,
    price      REAL,
    score      TEXT,
    lot_id     INTEGER,
    updated_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_manual ON manual_values(wine_key, COALESCE(vintage, -1));

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

LOT_FIELDS = [
    "title", "slug", "category_id", "image_url", "producer", "cuvee", "appellation", "vintage", "nv",
    "mixed", "bottles", "bottle_eq", "size_l", "wine_name", "wine_key", "parse_ok",
]


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(lots)")}
        for name, typ in (("rating", "REAL"), ("rating_count", "INTEGER"), ("rating_url", "TEXT"),
                          ("critic_score", "TEXT"), ("ship_it", "REAL"), ("ship_es", "REAL"), ("ship_any", "REAL"),
                          ("fee_pct", "REAL"), ("fee_fixed", "REAL"), ("details_at", "INTEGER"),
                          ("pickup_only", "INTEGER")):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE lots ADD COLUMN {name} {typ}")
        self.conn.commit()

    # ---------- kv ----------
    def get(self, key: str, default=None):
        r = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
        self.conn.commit()

    # ---------- lots ----------
    def upsert_listing(self, lot: dict) -> None:
        now = int(time.time())
        cols = ["id"] + LOT_FIELDS
        vals = [lot.get(c) for c in cols]
        upd = ", ".join(f"{c}=COALESCE(excluded.{c}, lots.{c})" for c in LOT_FIELDS)  # i nuovi valori vincono
        self.conn.execute(
            f"INSERT INTO lots({','.join(cols)}, first_seen, last_seen) VALUES({','.join('?' * len(cols))}, ?, ?) "
            f"ON CONFLICT(id) DO UPDATE SET {upd}, last_seen=excluded.last_seen",
            vals + [now, now],
        )

    def update_live(self, lot_id: int, data: dict) -> None:
        sets, vals = [], []
        for k in ("current_bid", "currency", "end_time", "reserve_set", "reserve_met", "close_status", "final", "sold"):
            if data.get(k) is not None:
                sets.append(f"{k}=?")
                vals.append(data[k])
        if sets:
            self.conn.execute(f"UPDATE lots SET {', '.join(sets)} WHERE id=?", vals + [lot_id])

    def set_estimate(self, lot_id: int, low, high) -> None:
        self.conn.execute(
            "UPDATE lots SET estimate_low=?, estimate_high=?, estimate_checked=1 WHERE id=?", (low, high, lot_id)
        )

    def save_score(self, lot_id: int, s: dict) -> None:
        self.conn.execute(
            "UPDATE lots SET market_per_bottle=?, cost_per_bottle=?, discount=?, confidence=?, value_source=?, "
            "max_bid=?, scored_at=?, rating=?, rating_count=?, rating_url=?, critic_score=? WHERE id=?",
            (s.get("market_per_bottle"), s.get("cost_per_bottle"), s.get("discount"), s.get("confidence"),
             s.get("value_source"), s.get("max_bid"), int(time.time()), s.get("rating"), s.get("rating_count"),
             s.get("rating_url"), s.get("critic_score"), lot_id),
        )

    def commit(self) -> None:
        self.conn.commit()

    def open_lots(self, within_hours: float | None = None) -> list[sqlite3.Row]:
        now = int(time.time())
        q = "SELECT * FROM lots WHERE final=0 AND (end_time IS NULL OR end_time > ?)"
        args: list = [now - 300]
        if within_hours:
            q += " AND end_time IS NOT NULL AND end_time <= ?"
            args.append(now + int(within_hours * 3600))
        return self.conn.execute(q + " ORDER BY end_time", args).fetchall()

    def lots_to_finalize(self) -> list[int]:
        now = int(time.time())
        rows = self.conn.execute(
            "SELECT id FROM lots WHERE final=0 AND end_time IS NOT NULL AND end_time < ?", (now - 120,)
        ).fetchall()
        return [r["id"] for r in rows]

    def history(self, since_days: int) -> list[sqlite3.Row]:
        since = int(time.time()) - since_days * 86400
        return self.conn.execute(
            "SELECT id, wine_key, wine_name, vintage, nv, bottle_eq, current_bid, end_time FROM lots "
            "WHERE final=1 AND sold=1 AND parse_ok=1 AND current_bid>0 AND bottle_eq>0 AND end_time>=?",
            (since,),
        ).fetchall()

    def sold_history(self, limit: int = 500) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM lots WHERE final=1 AND sold=1 AND current_bid>0 ORDER BY end_time DESC LIMIT ?", (limit,)
        ).fetchall()

    def stats(self) -> dict:
        c = self.conn
        return {
            "tracciati": c.execute("SELECT COUNT(*) FROM lots").fetchone()[0],
            "aperti": c.execute("SELECT COUNT(*) FROM lots WHERE final=0").fetchone()[0],
            "storico_venduti": c.execute("SELECT COUNT(*) FROM lots WHERE final=1 AND sold=1").fetchone()[0],
            "avvisi_inviati": c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0],
        }

    # ---------- alerts ----------
    def was_alerted(self, lot_id: int, kind: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM alerts WHERE lot_id=? AND kind=?", (lot_id, kind)
        ).fetchone() is not None

    def mark_alerted(self, lot_id: int, kind: str, discount: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO alerts(lot_id, kind, sent_at, discount) VALUES(?,?,?,?)",
            (lot_id, kind, int(time.time()), discount),
        )
        self.conn.commit()
