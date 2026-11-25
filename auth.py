"""教材用のトークンと利用者の対応。固定値なので本番では使わない。"""

from datetime import date

from mcp.server.mcpserver.exceptions import ToolError

# トークン → 利用者。role は applicant(申請者)か keiri(経理担当)
TOKENS = {
    "tatekae-alice-2026": {"name": "alice", "role": "applicant", "expires": date(2099, 12, 31)},
    "tatekae-bob-2026": {"name": "bob", "role": "applicant", "expires": date(2099, 12, 31)},
    "tatekae-keiri-2026": {"name": "keiri", "role": "keiri", "expires": date(2099, 12, 31)},
    "tatekae-alice-2025": {"name": "alice", "role": "applicant", "expires": date(2025, 3, 31)},  # 失効
}


def authenticate(authorization: str | None) -> dict:
    """Authorization ヘッダー(Bearer トークン)から利用者を返す。確かめられなければ ToolError。"""
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = TOKENS.get(token)
    if user is None:
        raise ToolError("認証エラー: トークンが無いか、正しくありません。.mcp.json の Authorization ヘッダーを確かめてください。")
    if user["expires"] < date.today():
        raise ToolError(f"認証エラー: トークンは {user['expires']} に失効しています。新しいトークンに替えてください。")
    return user
