# tatekae

経費精算の領収書を扱うMCPサーバー(研修教材)。

## 構成

- `server.py`: 道具の定義(MCP SDK 2.x の `MCPServer`)。道具は `search_receipts` / `get_receipt` / `add_receipt` / `delete_receipt` / `export_receipts`
- `auth.py`: 教材用トークンと利用者(alice・bob・keiri)の対応。トークンは `.mcp.json` の `Authorization` ヘッダーで渡す
- `db.py`: SQLite(`tatekae.db`)の読み書き。領収書は起動時に `data/receipts.csv` から読み直す
- `data/receipts.csv`: 架空の領収書データ
- `tests/`: 通常機能の確認(`test_basic.py`)。`test_security.py` は受講者が書く
- `logs/sample-server.log`: サーバーログの見本
- `report.md`・`evidence/`: 受講者が書く報告と証跡

## コマンド

- 起動: `uv run server.py`(`http://127.0.0.1:8000/mcp`)
- テスト: `uv run pytest`

## 守ること

- 道具の名前と引数は変えない。採点のテストで使う
- 依存を足すときは `uv add` を使い、`pyproject.toml` と `uv.lock` を一緒に更新する
- `README.md`・`AGENTS.md`・`data/`・`tests/conftest.py`・`tests/test_basic.py` は書き換えない。採点では `tests/conftest.py` と `tests/test_basic.py` を雛形の物に戻す
- `auth.py` のトークンは採点のテストが使うので、値を変えたり消したりしない
