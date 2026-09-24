"""记录发起生成的客户端；重试和跨端保存不改变来源。"""
from pathlib import Path

CLIENTS = {"mobile", "desktop", "web"}


def record_origin(folder: Path, client: str) -> None:
    client = client.strip().lower()
    marker = folder / "generation_client"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            stream.write(client if client in CLIENTS else "unknown")
    except FileExistsError:
        pass


def read_origin(folder: Path | None) -> str | None:
    if folder is None:
        return None
    try:
        client = (folder / "generation_client").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        # 来源仅为显示备注；历史标记损坏不应阻断纪要保存。
        return None
    return client if client in CLIENTS else None
