"""SQLite の読み書き。DBファイルは tatekae.db(コミットしない)。"""

import csv
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "tatekae.db"
RECEIPTS_CSV = HERE / "data" / "receipts.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    date TEXT NOT NULL,
    vendor TEXT NOT NULL,
    amount INTEGER NOT NULL,
    category TEXT NOT NULL,
    memo TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def fingerprint(date: str, vendor: str, amount) -> str:
    """同じ日・店・金額の領収書を見つけるための指紋。重複の警告だけに使う。"""
    return hashlib.md5(f"{date}|{vendor}|{amount}".encode()).hexdigest()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    """表を作り直し、receipts を data/receipts.csv から読み込む。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM receipts")
        with open(RECEIPTS_CSV, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                con.execute(
                    "INSERT INTO receipts (owner, date, vendor, amount, category, memo, fingerprint, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["owner"],
                        row["date"],
                        row["vendor"],
                        int(row["amount"]),
                        row["category"],
                        row["memo"],
                        fingerprint(row["date"], row["vendor"], int(row["amount"])),
                        now,
                    ),
                )
    con.close()


_COLUMNS = "id, owner, date, vendor, amount, category, memo, created_at"


def search_receipts(owner: str, query: str, limit: int = 10, all_owners: bool = False) -> list[dict]:
    where = f"(vendor LIKE '%{query}%' OR memo LIKE '%{query}%')"
    if not all_owners:
        where = f"owner = '{owner}' AND {where}"
    sql = f"SELECT {_COLUMNS} FROM receipts WHERE {where} LIMIT {limit}"
    with connect() as con:
        rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return rows


def get_receipt(receipt_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(f"SELECT {_COLUMNS} FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def month_receipts(owner: str, month: str) -> list[dict]:
    with connect() as con:
        rows = [
            dict(r)
            for r in con.execute(
                f"SELECT {_COLUMNS} FROM receipts WHERE owner = ? AND date LIKE ? ORDER BY id",
                (owner, f"{month}%"),
            )
        ]
    con.close()
    return rows


def add_receipt(owner: str, date: str, vendor: str, amount: int, category: str, memo: str) -> dict:
    fp = fingerprint(date, vendor, amount)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        duplicate = con.execute(
            "SELECT id FROM receipts WHERE owner = ? AND fingerprint = ?", (owner, fp)
        ).fetchone()
        cur = con.execute(
            "INSERT INTO receipts (owner, date, vendor, amount, category, memo, fingerprint, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (owner, date, vendor, amount, category, memo, fp, created_at),
        )
        receipt = {
            "id": cur.lastrowid,
            "owner": owner,
            "date": date,
            "vendor": vendor,
            "amount": amount,
            "category": category,
            "memo": memo,
            "created_at": created_at,
        }
    con.close()
    return receipt, (duplicate is not None)


def delete_receipt(receipt_id: int) -> bool:
    """消せたら True。その番号の領収書が無ければ False。"""
    with connect() as con:
        deleted = con.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,)).rowcount
    con.close()
    return deleted == 1
