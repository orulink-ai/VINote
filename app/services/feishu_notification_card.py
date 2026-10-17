"""Compact document notifications; full content stays in the document."""


def document_card(title, destination, document_url):
    path = destination.get("path") if isinstance(destination, dict) else None
    names = [name.strip() for name in path if isinstance(name, str) and name.strip()] if isinstance(path, list) else []
    location = " / ".join(names) or "飞书云文档"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
        "elements": [
            {"tag": "div", "text": {"tag": "plain_text", "content": "已发布至：" + location}},
            {"tag": "action", "actions": [{
                "tag": "button", "text": {"tag": "plain_text", "content": "打开文档"},
                "url": document_url, "type": "primary",
            }]},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "由 VINote 发布"}]},
        ],
    }
