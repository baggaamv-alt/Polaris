"""Append-only, hash-chained audit log (F-64) in SQLite."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

GENESIS = b"\x00" * 32


def _canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


class AuditLog:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, sim_t REAL, entry_type TEXT NOT NULL,
            actor TEXT NOT NULL, body TEXT NOT NULL, prev_hash BLOB NOT NULL, hash BLOB NOT NULL)""")
        self.db.commit()

    def append(self, entry_type: str, actor: str, body: dict, sim_t: float | None = None) -> int:
        with self.lock:
            row = self.db.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            payload = {"entry_type": entry_type, "actor": actor, "sim_t": sim_t, "body": body}
            h = hashlib.sha256(prev + _canon(payload)).digest()
            cur = self.db.execute(
                "INSERT INTO audit_log (ts, sim_t, entry_type, actor, body, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                (time.time(), sim_t, entry_type, actor, json.dumps(body, default=str), prev, h))
            self.db.commit()
            return int(cur.lastrowid)

    def list(self, limit: int = 200, entry_type: str | None = None) -> list[dict]:
        q = "SELECT seq, ts, sim_t, entry_type, actor, body, hash FROM audit_log"
        args: tuple = ()
        if entry_type:
            q += " WHERE entry_type = ?"
            args = (entry_type,)
        q += " ORDER BY seq DESC LIMIT ?"
        with self.lock:
            rows = self.db.execute(q, args + (limit,)).fetchall()
        return [{"seq": r[0], "ts": r[1], "sim_t": r[2], "entry_type": r[3], "actor": r[4],
                 "body": json.loads(r[5]), "hash": r[6].hex()[:16]} for r in rows]

    def get(self, seq: int) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT seq, ts, sim_t, entry_type, actor, body FROM audit_log WHERE seq=?",
                                (seq,)).fetchone()
        return None if r is None else {"seq": r[0], "ts": r[1], "sim_t": r[2], "entry_type": r[3], "actor": r[4],
                                       "body": json.loads(r[5])}

    def verify(self) -> dict:
        with self.lock:
            rows = self.db.execute(
                "SELECT seq, sim_t, entry_type, actor, body, prev_hash, hash FROM audit_log ORDER BY seq").fetchall()
        prev = GENESIS
        for seq, sim_t, et, actor, body, ph, h in rows:
            payload = {"entry_type": et, "actor": actor, "sim_t": sim_t, "body": json.loads(body)}
            if ph != prev or hashlib.sha256(prev + _canon(payload)).digest() != h:
                return {"ok": False, "broken_at": seq, "entries": len(rows)}
            prev = h
        return {"ok": True, "entries": len(rows)}
