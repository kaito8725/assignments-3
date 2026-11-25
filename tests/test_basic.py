"""通常機能のテスト: 正しい利用で道具が動く。雛形の時点で全部通る。

種データ(data/receipts.csv): alice の領収書 id 1〜6、bob の領収書 id 7〜14。
"""

from conftest import payload, rows

ALICE = "tatekae-alice-2026"
BOB = "tatekae-bob-2026"
KEIRI = "tatekae-keiri-2026"
ALICE_EXPIRED = "tatekae-alice-2025"


def test_search_returns_matching_receipts(call):
    hits = rows(call("search_receipts", {"query": "カフェ"}, token=ALICE))
    assert any("カフェ" in h["vendor"] for h in hits)


def test_search_scoped_to_owner(call):
    hits = rows(call("search_receipts", {"query": "架空"}, token=ALICE))
    assert hits
    assert all(h["owner"] == "alice" for h in hits)


def test_search_limit_applies(call):
    hits = rows(call("search_receipts", {"query": "架空", "limit": 2}, token=ALICE))
    assert len(hits) == 2


def test_get_own_receipt(call):
    receipt = payload(call("get_receipt", {"receipt_id": 1}, token=ALICE))
    assert receipt["owner"] == "alice"
    assert receipt["id"] == 1


def test_keiri_can_get_any_receipt(call):
    """経理担当は全員の領収書を取得できる(正しい姿)。"""
    receipt = payload(call("get_receipt", {"receipt_id": 7}, token=KEIRI))
    assert receipt["owner"] == "bob"


def test_add_receipt(call):
    result = payload(call(
        "add_receipt",
        {"date": "2026-11-25", "vendor": "架空書店", "amount": 500, "category": "書籍", "memo": "文庫本"},
        token=ALICE,
    ))
    assert result["receipt"]["owner"] == "alice"
    assert result["receipt"]["amount"] == 500
    assert "warning" not in result


def test_add_duplicate_warns(call):
    args = {"date": "2026-11-25", "vendor": "架空書店", "amount": 500, "category": "書籍", "memo": "文庫本"}
    call("add_receipt", args, token=ALICE)
    result = payload(call("add_receipt", args, token=ALICE))
    assert "warning" in result


def test_delete_own_receipt(call):
    added = payload(call(
        "add_receipt",
        {"date": "2026-11-26", "vendor": "架空店", "amount": 100, "category": "消耗品", "memo": "テスト"},
        token=ALICE,
    ))
    result = call("delete_receipt", {"receipt_id": added["receipt"]["id"]}, token=ALICE)
    assert not result.is_error


def test_export_writes_cp932_csv(call):
    result = payload(call("export_receipts", {"month": "2026-11"}, token=ALICE))
    assert result["count"] == 6
    with open(result["path"], encoding="cp932") as f:
        text = f.read()
    assert "O'Hara 書店" in text  # CP932 に変換した本文が読める


def test_expired_token_rejected(call):
    result = call("search_receipts", {"query": "架空"}, token=ALICE_EXPIRED)
    assert result.is_error
    assert "認証エラー" in result.content[0].text


def test_no_token_rejected(call):
    assert call("search_receipts", {"query": "架空"}).is_error
