"""tatekae: 経費精算の領収書を扱うMCPサーバー(研修教材)。

起動: uv run server.py  (http://127.0.0.1:8000/mcp)
"""

import csv
import logging
import subprocess
import tempfile
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import auth
import db

log = logging.getLogger("tatekae")
mcp = MCPServer("tatekae")

HERE = Path(__file__).parent
EXPORT_DIR = HERE / "exports"
EXPORT_HEADER = ["id", "date", "vendor", "amount", "category", "memo"]


def current_user(ctx: Context) -> dict:
    """呼び出した人を Authorization ヘッダーのトークンで確かめる(認証)。"""
    authorization = (ctx.headers or {}).get("authorization")
    log.info("call authorization=%s", authorization)
    user = auth.authenticate(authorization)
    log.info("call user=%s", user["name"])
    return user


@mcp.tool()
def search_receipts(query: str, ctx: Context, limit: int = 10) -> list[dict]:
    """自分の領収書を店名かメモの言葉で検索し、一致した領収書の一覧を返す。

    query: 探したい言葉(店名かメモ)
    limit: 返す件数の上限(1〜20)
    """
    user = current_user(ctx)
    return db.search_receipts(user["name"], query, limit, all_owners=(user["role"] == "keiri"))


@mcp.tool()
def get_receipt(receipt_id: int, ctx: Context) -> dict:
    """領収書を番号で1件取得する。

    receipt_id: 取得する領収書の番号
    """
    current_user(ctx)
    receipt = db.get_receipt(receipt_id)
    if receipt is None:
        raise ToolError(f"番号 {receipt_id} の領収書はありません。")
    return receipt


@mcp.tool()
def add_receipt(date: str, vendor: str, amount: int, category: str, memo: str, ctx: Context) -> dict:
    """領収書を1件登録し、登録した領収書を返す。同じ日・店・金額の領収書があれば警告を添える。

    date: 日付(例: 2026-11-20)
    vendor: 店名
    amount: 金額(円、1以上)
    category: 費目(例: 会議費・旅費交通費・消耗品)
    memo: メモ
    """
    user = current_user(ctx)
    receipt, is_duplicate = db.add_receipt(user["name"], date, vendor, amount, category, memo)
    log.info(
        "add_receipt id=%s owner=%s vendor=%s amount=%s memo=%s",
        receipt["id"], user["name"], vendor, amount, memo,
    )
    result = {"receipt": receipt}
    if is_duplicate:
        result["warning"] = "同じ日・店・金額の領収書がすでにあります。二重計上でないか確かめてください。"
    return result


@mcp.tool()
def delete_receipt(receipt_id: int, ctx: Context) -> str:
    """領収書を番号で1件消す。消した領収書は元に戻せない。

    receipt_id: 消す領収書の番号
    """
    current_user(ctx)
    if not db.delete_receipt(receipt_id):
        raise ToolError(f"番号 {receipt_id} の領収書はありません。")
    return f"領収書 {receipt_id} を消しました。"


@mcp.tool()
def export_receipts(month: str, ctx: Context) -> dict:
    """指定した月の自分の領収書を、会計ソフト向けの Shift_JIS(CP932)の CSV に書き出す。

    month: 対象の月(例: 2026-11)
    """
    user = current_user(ctx)
    rows = db.month_receipts(user["name"], month)

    EXPORT_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as tmp:
        writer = csv.writer(tmp)
        writer.writerow(EXPORT_HEADER)
        for r in rows:
            writer.writerow([r[c] for c in EXPORT_HEADER])
        tmp_csv = tmp.name

    out_path = f"{EXPORT_DIR}/{user['name']}-{month}.csv"
    # UTF-8 の一時CSVを CP932 に変換して書き出す
    subprocess.run(f"iconv -f UTF-8 -t CP932 {tmp_csv} > {out_path}", shell=True, check=True)
    return {"path": out_path, "count": len(rows)}


if __name__ == "__main__":
    db.init_db()
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)  # パスは既定の /mcp
