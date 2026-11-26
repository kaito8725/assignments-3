"""tatekae: 経費精算の領収書を扱うMCPサーバー(研修教材)。

起動: uv run server.py  (http://127.0.0.1:8000/mcp)
"""

import csv
import io
import logging
import re
from datetime import datetime
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
SEARCH_LIMIT_MAX = 20
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def current_user(ctx: Context) -> dict:
    """呼び出した人を Authorization ヘッダーのトークンで確かめる(認証)。"""
    authorization = (ctx.headers or {}).get("authorization")
    # トークンはログに出さない
    user = auth.authenticate(authorization)
    log.info("call user=%s", user["name"])
    return user


def require_applicant(user: dict) -> None:
    """申請者だけに許す操作。経理担当(確認だけの役割)は拒否する。"""
    if user["role"] != "applicant":
        raise ToolError("権限エラー: この操作は申請者だけができます。経理担当は確認だけです。")


def not_found(receipt_id: int) -> ToolError:
    """無い番号と他人の番号で同じ答え方をする(番号の存在を漏らさない)。"""
    return ToolError(f"番号 {receipt_id} の領収書はありません。")


def can_access(user: dict, receipt: dict | None) -> bool:
    return receipt is not None and (user["role"] == "keiri" or receipt["owner"] == user["name"])


@mcp.tool()
def search_receipts(query: str, ctx: Context, limit: int = 10) -> list[dict]:
    """自分の領収書を店名かメモの言葉で検索し、一致した領収書の一覧を返す。

    query: 探したい言葉(店名かメモ)
    limit: 返す件数の上限(1〜20)
    """
    user = current_user(ctx)
    if not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ToolError(f"入力エラー: limit は 1〜{SEARCH_LIMIT_MAX} で指定してください。")
    return db.search_receipts(user["name"], query, limit, all_owners=(user["role"] == "keiri"))


@mcp.tool()
def get_receipt(receipt_id: int, ctx: Context) -> dict:
    """領収書を番号で1件取得する。

    receipt_id: 取得する領収書の番号
    """
    user = current_user(ctx)
    receipt = db.get_receipt(receipt_id)
    if not can_access(user, receipt):
        raise not_found(receipt_id)
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
    require_applicant(user)
    if amount < 1:
        raise ToolError("入力エラー: amount は 1 以上の整数で指定してください。")
    if not valid_date(date):
        raise ToolError("入力エラー: date は YYYY-MM-DD の形の正しい日付で指定してください(例: 2026-11-20)。")
    receipt, is_duplicate = db.add_receipt(user["name"], date, vendor, amount, category, memo)
    # メモ(同席者の氏名などの個人情報)はログに出さない
    log.info("add_receipt id=%s owner=%s amount=%s", receipt["id"], user["name"], amount)
    result = {"receipt": receipt}
    if is_duplicate:
        result["warning"] = "同じ日・店・金額の領収書がすでにあります。二重計上でないか確かめてください。"
    return result


@mcp.tool()
def delete_receipt(receipt_id: int, ctx: Context) -> str:
    """領収書を番号で1件消す。消した領収書は元に戻せない。

    receipt_id: 消す領収書の番号
    """
    user = current_user(ctx)
    require_applicant(user)
    if not can_access(user, db.get_receipt(receipt_id)) or not db.delete_receipt(receipt_id):
        raise not_found(receipt_id)
    return f"領収書 {receipt_id} を消しました。"


@mcp.tool()
def export_receipts(month: str, ctx: Context) -> dict:
    """指定した月の自分の領収書を、会計ソフト向けの Shift_JIS(CP932)の CSV に書き出す。

    month: 対象の月(例: 2026-11)
    """
    user = current_user(ctx)
    require_applicant(user)
    if not MONTH_RE.fullmatch(month):
        raise ToolError("入力エラー: month は YYYY-MM の形で指定してください(例: 2026-11)。")
    rows = db.month_receipts(user["name"], month)

    # シェルも一時ファイルも使わず、メモリ上で CSV を作って CP932 で書き出す
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADER)
    for r in rows:
        writer.writerow([r[c] for c in EXPORT_HEADER])
    try:
        data = buf.getvalue().encode("cp932")
    except UnicodeEncodeError:
        raise ToolError("書き出しエラー: CP932 で表せない文字を含む領収書があります。")

    EXPORT_DIR.mkdir(exist_ok=True)
    out_path = EXPORT_DIR / f"{user['name']}-{month}.csv"
    out_path.write_bytes(data)
    return {"path": str(out_path), "count": len(rows)}


def valid_date(value: str) -> bool:
    """YYYY-MM-DD の形で、実在する日付なら True。"""
    if not DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    db.init_db()
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)  # パスは既定の /mcp
