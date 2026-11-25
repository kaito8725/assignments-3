# tatekae(立替)

経費精算の領収書を扱うMCPサーバーです。申請者は自分の領収書を追加・検索・取得・削除・書き出しでき、経理担当は全員の領収書を確認します。

データはすべて架空です(`data/README.md`)。

## 起動

```
uv sync
uv run server.py
```

`http://127.0.0.1:8000/mcp` で待ち受けます。Claude Code からは `.mcp.json` でつなぎます。トークンは環境変数 `TATEKAE_TOKEN` に入れます。

## トークン

| 利用者 | 役割 | トークン |
|---|---|---|
| alice | 申請者 | `tatekae-alice-2026` |
| bob | 申請者 | `tatekae-bob-2026` |
| keiri | 経理担当 | `tatekae-keiri-2026` |

申請者は自分の領収書だけを扱い、経理担当は全員の領収書を確認します。

## 道具

| 道具 | 引数 | 返す物 |
|---|---|---|
| `search_receipts` | `query`(店名かメモの言葉)、`limit` | 一致した領収書の一覧 |
| `get_receipt` | `receipt_id` | 領収書1件 |
| `add_receipt` | `date`、`vendor`、`amount`、`category`、`memo` | 登録した領収書と、重複の警告(あれば) |
| `delete_receipt` | `receipt_id` | 消した旨の文 |
| `export_receipts` | `month`(例: `2026-11`) | 書き出した CSV の場所と件数 |

`export_receipts` は会計ソフト向けに Shift_JIS(CP932)の CSV を `exports/` に書き出します。

## テスト

```
uv run pytest
```
