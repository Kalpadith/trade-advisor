"""SQLite candle cache. One row per (market, symbol, interval, open_time);
upserts make incremental sync idempotent. Connections are opened per
operation so the store is safe to use from FastAPI's threadpool without
shared-connection locking."""

import sqlite3
from pathlib import Path

import pandas as pd

from tradeadvisor.models import Candle

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles(
    market TEXT NOT NULL DEFAULT 'spot',
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    close_time INTEGER NOT NULL,
    PRIMARY KEY(market, symbol, interval, open_time)
) WITHOUT ROWID;
"""

COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


class CandleStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            self._migrate(con)
            con.execute(SCHEMA)

    @staticmethod
    def _migrate(con: sqlite3.Connection) -> None:
        """The store is a pure cache: if an older schema (no market column)
        is found, drop it and refetch rather than migrating rows."""
        cols = [r[1] for r in con.execute("PRAGMA table_info(candles)").fetchall()]
        if cols and "market" not in cols:
            con.execute("DROP TABLE candles")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def upsert(self, symbol: str, interval: str, candles: list[Candle], market: str = "spot") -> int:
        if not candles:
            return 0
        rows = [
            (market, symbol.upper(), interval, c.open_time,
             c.open, c.high, c.low, c.close, c.volume, c.close_time)
            for c in candles
        ]
        with self._connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)", rows
            )
        return len(rows)

    def load(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
        market: str = "spot",
    ) -> pd.DataFrame:
        """Return candles as a DataFrame with a UTC DatetimeIndex, oldest first.
        `limit` keeps only the most recent N rows of the selected range."""
        query = (
            "SELECT open_time, open, high, low, close, volume, close_time "
            "FROM candles WHERE market=? AND symbol=? AND interval=?"
        )
        params: list = [market, symbol.upper(), interval]
        if start_ms is not None:
            query += " AND open_time >= ?"
            params.append(int(start_ms))
        if end_ms is not None:
            query += " AND open_time <= ?"
            params.append(int(end_ms))
        query += " ORDER BY open_time DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as con:
            df = pd.read_sql_query(query, con, params=params)
        df = df.iloc[::-1].reset_index(drop=True)
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.index.name = "time"
        return df

    def latest_open_time(self, symbol: str, interval: str, market: str = "spot") -> int | None:
        return self._edge_open_time(symbol, interval, "MAX", market)

    def earliest_open_time(self, symbol: str, interval: str, market: str = "spot") -> int | None:
        return self._edge_open_time(symbol, interval, "MIN", market)

    def _edge_open_time(self, symbol: str, interval: str, agg: str, market: str) -> int | None:
        with self._connect() as con:
            row = con.execute(
                f"SELECT {agg}(open_time) FROM candles WHERE market=? AND symbol=? AND interval=?",
                (market, symbol.upper(), interval),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def count(self, symbol: str, interval: str, market: str = "spot") -> int:
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM candles WHERE market=? AND symbol=? AND interval=?",
                (market, symbol.upper(), interval),
            ).fetchone()
        return int(row[0])
