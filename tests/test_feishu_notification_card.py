from app.services.feishu_notification_card import document_card


def test_document_notification_keeps_title_and_location_without_raw_body():
    card = document_card("会议纪要 · 产品评审", {"path": ["项目资料", "评审"]}, "https://example.feishu.cn/docx/test")
    assert card["header"]["title"] == {"tag": "plain_text", "content": "会议纪要 · 产品评审"}
    assert card["elements"][0]["text"]["content"] == "已发布至：项目资料 / 评审"
    button = card["elements"][1]["actions"][0]
    assert button["text"]["content"] == "打开文档"
    assert button["url"] == "https://example.feishu.cn/docx/test"
    assert "版本" not in str(card)


def test_legacy_destination_does_not_expose_technical_identifiers():
    card = document_card("笔记", {"kind": "folder", "folder_token": "private-token", "path": None}, "https://example.feishu.cn/docx/test")
    assert card["elements"][0]["text"]["content"] == "已发布至：飞书云文档"
    assert "private-token" not in str(card)
