"""记录统一账号的登录终端，不保存密码、令牌或设备标识。"""
from app.db import session_scope
from app.db_models import AuthLoginEventDB


def record_login(user_id, request):
    client = request.headers.get("X-VINote-Client", "unknown").lower()
    platform = request.headers.get("X-VINote-Platform", "unknown").lower()
    if client not in {"mobile", "desktop", "web"}:
        client = "unknown"
    if platform not in {"android", "ios", "windows", "macos", "linux", "web"}:
        platform = "unknown"
    with session_scope() as db:
        db.add(AuthLoginEventDB(user_id=user_id, client=client, platform=platform))
