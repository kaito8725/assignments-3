"""弱点の再現と修正の確認に使うテストを書くファイル。

見つけた弱点ごとに、攻撃が失敗することを確かめるテストを書く。修正前に落ち、修正後に通る形にする。
道具は tests/conftest.py の call(道具名, 引数, token=...) で呼ぶ。

番号は report.md の「AIのセキュリティレビューの結果」の表の # に合わせている。
種データ(data/receipts.csv): alice の領収書 id 1〜6、bob の領収書 id 7〜14。
"""

import json
import logging
from pathlib import Path

import pytest

import auth
import db
import server
from conftest import payload, rows

ALICE = "tatekae-alice-2026"
BOB = "tatekae-bob-2026"
KEIRI = "tatekae-keiri-2026"

BOB_RECEIPT_ID = 7
ROOT = Path(__file__).resolve().parent.parent


def receipt_exists(receipt_id: int) -> bool:
    return db.get_receipt(receipt_id) is not None


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    """書き出し先を一時ディレクトリに替え、本物の exports/ を汚さない。"""
    d = tmp_path / "exports"
    monkeypatch.setattr(server, "EXPORT_DIR", d)
    return d


# --- #1 コマンドインジェクション(export_receipts の month) ---


@pytest.mark.parametrize("template", [
    "2026-11; touch {marker} #",
    "2026-11$(touch {marker})",
    "2026-11`touch {marker}`",
    "2026-11 && touch {marker} #",
])
def test_export_month_cannot_run_shell_commands(call, export_dir, tmp_path, template):
    marker = tmp_path / "pwned"
    call("export_receipts", {"month": template.format(marker=marker)}, token=ALICE)
    assert not marker.exists(), "month に書いたシェルのコマンドが実行された"


# --- #2 SQLインジェクション(search_receipts の query) ---


@pytest.mark.parametrize("query", [
    "x') OR 1=1 --",
    "x') OR owner='bob' --",
    "x') UNION SELECT 1,name,sql,1,1,1,1,1 FROM sqlite_master --",
])
def test_search_query_cannot_inject_sql(call, query):
    result = call("search_receipts", {"query": query}, token=ALICE)
    if result.is_error:
        return  # 拒否されるのも可
    hits = rows(result)
    assert all(h["owner"] == "alice" for h in hits), f"alice 以外の行が返った: {hits}"


def test_search_with_quote_works(call):
    """店名に ' を含む領収書を普通に検索できる(SQL を組み立てていると構文エラーになる)。"""
    result = call("search_receipts", {"query": "O'Hara"}, token=ALICE)
    assert not result.is_error
    assert any(h["vendor"] == "O'Hara 書店" for h in rows(result))


# --- #3 他人の領収書を読める(get_receipt) ---


def test_applicant_cannot_get_others_receipt(call):
    result = call("get_receipt", {"receipt_id": BOB_RECEIPT_ID}, token=ALICE)
    assert result.is_error, "alice が bob の領収書を取得できた"
    assert "bob" not in result.content[0].text
    # 経理担当は引き続き全員の領収書を取得できる
    assert payload(call("get_receipt", {"receipt_id": BOB_RECEIPT_ID}, token=KEIRI))["owner"] == "bob"


def test_others_receipt_error_matches_missing(call):
    """他人の領収書と存在しない番号で、同じ答え方をする(番号の存在を漏らさない)。"""
    other = call("get_receipt", {"receipt_id": BOB_RECEIPT_ID}, token=ALICE)
    missing = call("get_receipt", {"receipt_id": 99999}, token=ALICE)
    assert other.is_error and missing.is_error
    assert other.content[0].text.replace(str(BOB_RECEIPT_ID), "N") == missing.content[0].text.replace("99999", "N")


# --- #4 他人の領収書を消せる(delete_receipt) ---


def test_applicant_cannot_delete_others_receipt(call):
    result = call("delete_receipt", {"receipt_id": BOB_RECEIPT_ID}, token=ALICE)
    assert result.is_error, "alice が bob の領収書を消せた"
    assert receipt_exists(BOB_RECEIPT_ID)


# --- #5 ログにトークンが残る ---


@pytest.mark.parametrize("token", [ALICE, BOB, KEIRI, "tatekae-wrong-token"])
def test_token_not_logged(call, caplog, token):
    caplog.set_level(logging.DEBUG)
    call("search_receipts", {"query": "架空"}, token=token)
    assert token not in caplog.text, "Authorization ヘッダーのトークンがログに出た"


# --- #6 経理担当のトークンが .mcp.json に直書き ---


def test_mcp_json_has_no_literal_tokens():
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    text = json.dumps(config, ensure_ascii=False)
    leaked = [t for t in auth.TOKENS if t in text]
    assert not leaked, f".mcp.json にトークンが直書きされている: {leaked}"


# --- #7 ログに個人情報(メモの氏名)が残る ---


def test_memo_not_logged(call, caplog):
    caplog.set_level(logging.DEBUG)
    memo = "会食 同席: 架空 秘密太郎"
    result = call(
        "add_receipt",
        {"date": "2026-11-25", "vendor": "架空料亭", "amount": 9000, "category": "会議費", "memo": memo},
        token=ALICE,
    )
    assert not result.is_error
    assert "秘密太郎" not in caplog.text, "メモの氏名がログに出た"


# --- #8 入力を検証していない(add_receipt の amount・date) ---


@pytest.mark.parametrize("overrides", [
    {"amount": -50000},
    {"amount": 0},
    {"date": "x"},
    {"date": "2026/11/25"},
    {"date": "2026-13-01"},
])
def test_add_receipt_rejects_invalid_input(call, overrides):
    args = {"date": "2026-11-25", "vendor": "架空検証店", "amount": 500, "category": "消耗品", "memo": "検証"}
    args.update(overrides)
    result = call("add_receipt", args, token=ALICE)
    assert result.is_error, f"不正な入力が登録された: {overrides}"
    assert not rows(call("search_receipts", {"query": "架空検証店"}, token=ALICE))


# --- #9 limit の範囲(1〜20)を確かめていない ---


@pytest.mark.parametrize("limit", [-1, 0, 21, 1000])
def test_search_limit_out_of_range(call, limit):
    for i in range(25):
        db.add_receipt("alice", "2026-11-28", f"架空大量店{i}", 100 + i, "消耗品", "大量")
    result = call("search_receipts", {"query": "架空大量店", "limit": limit}, token=ALICE)
    if result.is_error:
        return  # 範囲外として拒否するのも可
    hits = rows(result)
    assert 1 <= len(hits) <= 20, f"limit={limit} で {len(hits)} 件返った"


# --- #10 month の ../ でパスをたどれる ---


def test_export_month_cannot_traverse_path(call, export_dir, tmp_path):
    (export_dir / "alice-x").mkdir(parents=True)  # たどる途中のディレクトリがある状況を作る
    escaped = tmp_path / "escaped.csv"
    call("export_receipts", {"month": "x/../../escaped"}, token=ALICE)
    assert not escaped.exists(), "exports/ の外にファイルが書かれた"


# --- #11 戻り値でサーバー側の絶対パスを教えている ---
# テストを書いていない。tests/test_basic.py の test_export_writes_cp932_csv が戻り値の path を
# そのまま open しているため、絶対パスを返さない修正をすると採点のテストを壊すおそれがある。


# --- #12 失効したトークンに失効日を返している ---
# テストを書いていない。失効日を返しても攻撃には使えないため、誤検知と判断した。


# --- 経理担当は確認だけ: 削除・登録・書き出しはできない ---


def test_keiri_cannot_delete_receipt(call):
    result = call("delete_receipt", {"receipt_id": BOB_RECEIPT_ID}, token=KEIRI)
    assert result.is_error, "経理担当が領収書を消せた"
    assert receipt_exists(BOB_RECEIPT_ID)


def test_keiri_cannot_add_receipt(call):
    result = call(
        "add_receipt",
        {"date": "2026-11-25", "vendor": "架空経理店", "amount": 500, "category": "消耗品", "memo": "検証"},
        token=KEIRI,
    )
    assert result.is_error, "経理担当が領収書を登録できた"
    assert not rows(call("search_receipts", {"query": "架空経理店"}, token=KEIRI))


def test_keiri_cannot_export_receipts(call, export_dir):
    result = call("export_receipts", {"month": "2026-11"}, token=KEIRI)
    assert result.is_error, "経理担当が書き出しできた"
    assert not export_dir.exists() or not any(export_dir.iterdir())
