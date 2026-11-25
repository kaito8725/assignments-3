"""テストの共通部品: 一時DBと、HTTP のヘッダー付きで tools/call を送る call。"""

import json

import pytest
from mcp import types
from starlette.testclient import TestClient

import db
import server


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


@pytest.fixture
def call():
    """call(道具名, 引数, token=...) で、Authorization ヘッダー付きの tools/call を1回送る。"""
    app = server.mcp.streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:

        def send(name, args=None, token=None):
            headers = {"Accept": "application/json, text/event-stream"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}
            response = client.post("/mcp", json=body, headers=headers)
            response.raise_for_status()
            return types.CallToolResult.model_validate(response.json()["result"])

        yield send


def rows(result):
    """list を返す道具(search_receipts)の結果を list[dict] で取り出す。"""
    return result.structured_content["result"]


def payload(result):
    """dict を返す道具(get_receipt・add_receipt・export_receipts)の結果を dict で取り出す。"""
    return json.loads(result.content[0].text)
