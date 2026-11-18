"""Lưu trữ SQLite (chế độ WAL: một tiến trình ghi, giao diện đọc song song).

Bảng:
  snapshots   - snapshot đã chuẩn hóa theo chu kỳ lấy mẫu; UNIQUE(symbol, ts, source) chống trùng
  quality_log - bộ đếm sự cố chất lượng dữ liệu theo ngày/nguồn
  status      - nhịp tim của bộ thu thập (kết nối, lần nhận tin cuối)
  picks       - danh sách "chốt trước" cho forward-test; trigger chặn sửa/xóa
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..neo_api.models import NUMERIC_FIELDS
from ..timeutil import TZ_NAME

META_COLS = ["symbol", "ts", "trade_date", "source", "phase", "q_flags", "ingest_ts"]
SNAP_COLS = META_COLS + NUMERIC_FIELDS

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshots (
    {", ".join(f"{c} TEXT" for c in META_COLS)},
    {", ".join(f"{c} REAL" for c in NUMERIC_FIELDS)},
    UNIQUE(symbol, ts, source)
);
CREATE INDEX IF NOT EXISTS ix_snap_date_sym ON snapshots(trade_date, symbol, ts);
CREATE TABLE IF NOT EXISTS quality_log (
    trade_date TEXT, source TEXT, issue TEXT, n INTEGER,
    PRIMARY KEY (trade_date, source, issue)
);
CREATE TABLE IF NOT EXISTS status (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS picks (
    run_id TEXT, as_of TEXT, symbol TEXT, rank INTEGER, is_pick INTEGER,
    net_score REAL, comp_score REAL, cost_p90_bps REAL, capital REAL,
    config_hash TEXT, created_at TEXT,
    PRIMARY KEY (run_id, symbol)
);
CREATE TRIGGER IF NOT EXISTS picks_no_update BEFORE UPDATE ON picks
BEGIN SELECT RAISE(ABORT, 'picks la bat bien: khong duoc sua'); END;
CREATE TRIGGER IF NOT EXISTS picks_no_delete BEFORE DELETE ON picks
BEGIN SELECT RAISE(ABORT, 'picks la bat bien: khong duoc xoa'); END;
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- snapshots ----------
    def insert_rows(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        ph = ",".join("?" for _ in SNAP_COLS)
        cur = self.conn.executemany(
            f"INSERT OR IGNORE INTO snapshots ({','.join(SNAP_COLS)}) VALUES ({ph})",
            [tuple(r.get(c) for c in SNAP_COLS) for r in rows],
        )
        self.conn.commit()
        return cur.rowcount

    def insert_frame(self, df: pd.DataFrame) -> int:
        d = df.copy()
        for c in ("ts", "ingest_ts"):
            if c in d and pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].dt.tz_convert(TZ_NAME).map(lambda x: None if pd.isna(x) else x.isoformat())
        recs = d.astype(object).where(d.notna(), None).to_dict("records")
        return self.insert_rows(recs)

    def read_snapshots(self, since: str | None = None, until: str | None = None,
                       symbols: list[str] | None = None) -> pd.DataFrame:
        q, args = "SELECT * FROM snapshots WHERE 1=1", []
        if since:
            q += " AND trade_date >= ?"; args.append(since)
        if until:
            q += " AND trade_date <= ?"; args.append(until)
        if symbols:
            q += f" AND symbol IN ({','.join('?' for _ in symbols)})"; args += symbols
        df = pd.read_sql_query(q + " ORDER BY ts, symbol", self.conn, params=args)
        return normalize_frame(df)

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])

    def trade_dates(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT trade_date FROM snapshots ORDER BY trade_date")]

    def sources(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT source FROM snapshots")]

    # ---------- chất lượng & trạng thái ----------
    def add_quality(self, trade_date: str, source: str, counts: dict[str, int]) -> None:
        for issue, n in counts.items():
            self.conn.execute(
                "INSERT INTO quality_log VALUES (?,?,?,?) "
                "ON CONFLICT(trade_date, source, issue) DO UPDATE SET n = n + excluded.n",
                (trade_date, source, issue, int(n)))
        self.conn.commit()

    def read_quality(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM quality_log ORDER BY trade_date, issue", self.conn)

    def set_status(self, **kv) -> None:
        for k, v in kv.items():
            self.conn.execute("INSERT INTO status VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                              (k, str(v)))
        self.conn.commit()

    def get_status(self) -> dict:
        return dict(self.conn.execute("SELECT k, v FROM status").fetchall())


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Chuyển cột thời gian về datetime có múi giờ VN; giữ nguyên các cột còn lại."""
    if df.empty:
        df["ts"] = pd.to_datetime(df.get("ts"), utc=True).dt.tz_convert(TZ_NAME) if "ts" in df else df.get("ts")
        return df
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601").dt.tz_convert(TZ_NAME)
    if "ingest_ts" in df:
        df["ingest_ts"] = pd.to_datetime(df["ingest_ts"], utc=True, format="ISO8601",
                                         errors="coerce").dt.tz_convert(TZ_NAME)
    return df
