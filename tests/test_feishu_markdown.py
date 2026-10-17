import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


from app.services import feishu_markdown as native
from app.services import feishu_service as module
legacy_tests = load("format_legacy_tests", ROOT / "tests/test_feishu_delivery.py")
legacy_tests.module = module
service = legacy_tests.service
from app.db_models import FeishuDeliveryDB
from app.models.feishu_destination import FeishuDeliveryDestinationDB, FeishuWriteBatchDB
from app.services import feishu_receipt_service as receipts


def paragraph(key, value="文字", **style):
    return {"block_id": key, "parent_id": "", "revision_id": 0, "block_type": 2,
            "text": {"elements": [{"text_run": {"content": value, "text_element_style": style}}]}}


def table_conversion():
    return {"first_level_block_ids": ["table", "after"], "blocks": [
        {"block_id": "table", "block_type": 31, "children": ["c1", "c2"],
         "table": {"cells": ["c1", "c2"], "property": {"row_size": 1, "column_size": 2,
                   "merge_info": [{"row_span": 1, "col_span": 1}]}}},
        {"block_id": "c1", "block_type": 32, "table_cell": {}, "children": ["t1"]},
        {"block_id": "c2", "block_type": 32, "table_cell": {}, "children": ["t2"]},
        paragraph("t1", "事实 | A", bold=True, italic=True),
        paragraph("t2", "原始链接", link={"url": "https%3A%2F%2Fexample.com"}, inline_code=True),
        paragraph("after", "后续正文", strikethrough=True)]}


def job_for(service, content="|A|B|\n|---|---|\n|x|y|", legacy=False, selective=False):
    data = service.enqueue("a", str(uuid.uuid4()), "标题", content)
    with module.session_scope() as db:
        row = db.get(FeishuDeliveryDB, data["id"])
        row.document_id = "doc"
        if legacy or not selective:
            meta = db.get(FeishuDeliveryDestinationDB, row.id)
            snap = json.loads(meta.snapshot)
            if legacy:
                snap.pop("body_format", None)
            else:
                snap["body_format"] = native.PROTOCOL
            meta.snapshot = json.dumps(snap)
        db.flush()
        db.expunge(row)
        return row


def fake_calls(service, monkeypatch, converted=None, fail=None):
    calls = []
    def request(method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/convert"):
            return converted or table_conversion()
        if fail:
            raise fail
        return {"block_id_relations": [{"temporary_block_id": b["block_id"], "block_id": "real-" + b["block_id"]}
                                        for b in kwargs["body"]["descendants"]]}
    monkeypatch.setattr(service, "request", request)
    monkeypatch.setattr(service, "granted_scopes", lambda row: {"docx:document", "docx:document.block:convert"})
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return calls


def test_table_and_inline_styles_preserved_without_mutation():
    converted = table_conversion()
    before = json.dumps(converted)
    plan = native.prepare_plan("source", converted)
    body = plan["batches"][0]["body"]
    assert body["children_id"] == ["table", "after"]
    assert len(body["descendants"]) == 6
    assert body["descendants"][0]["table"] == {"property": {"row_size": 1, "column_size": 2}}
    assert body["descendants"][2]["text"]["elements"][0]["text_run"]["content"] == "事实 | A"
    assert body["descendants"][2]["text"]["elements"][0]["text_run"]["text_element_style"] == {"bold": True, "italic": True}
    assert json.dumps(converted) == before
    assert uuid.UUID(plan["batches"][0]["client_token"]).version == 4


@pytest.mark.parametrize("defect", ["cycle", "duplicate", "missing", "orphan", "image", "dimensions", "empty_cell"])
def test_invalid_or_unsupported_tree_fails_before_write(defect):
    data = table_conversion()
    if defect == "cycle": data["blocks"][3]["children"] = ["table"]
    if defect == "duplicate": data["blocks"].append(paragraph("after"))
    if defect == "missing": data["blocks"][1]["children"] = ["absent"]
    if defect == "orphan": data["blocks"].append(paragraph("orphan"))
    if defect == "image": data["blocks"][-1]["block_type"] = 27
    if defect == "dimensions": data["blocks"][0]["table"]["property"]["column_size"] = 101
    if defect == "empty_cell": data["blocks"][1]["children"] = []
    with pytest.raises(native.FormatError): native.prepare_plan("source", data)


def test_batching_keeps_whole_table_and_root_offsets():
    data = table_conversion()
    texts = [paragraph(f"p{i}") for i in range(997)]
    data["blocks"] = texts + data["blocks"]
    data["first_level_block_ids"] = [b["block_id"] for b in texts] + data["first_level_block_ids"]
    batches = native.prepare_plan("source", data)["batches"]
    assert [b["offset"] for b in batches] == [0, 997]
    assert [len(b["body"]["descendants"]) for b in batches] == [997, 6]
    assert batches[1]["body"]["children_id"] == ["table", "after"]


def test_single_oversized_subtree_is_not_truncated():
    data = {"first_level_block_ids": ["list"], "blocks": [
        {"block_id": "list", "block_type": 12, "children": [f"p{i}" for i in range(1000)]},
        *[paragraph(f"p{i}") for i in range(1000)]]}
    with pytest.raises(native.FormatError, match="single subtree"): native.prepare_plan("source", data)


def test_frozen_plan_survives_converter_change(service, monkeypatch):
    job = job_for(service)
    calls = fake_calls(service, monkeypatch)
    first = service.prepare_native_body("a", job)
    monkeypatch.setattr(service, "request", lambda *args, **kwargs: pytest.fail("must use frozen plan"))
    assert service.prepare_native_body("a", job) == first
    assert len(calls) == 1


def test_checkpoint_loss_does_not_rewrite_confirmed_batch(service, monkeypatch):
    job = job_for(service)
    calls = fake_calls(service, monkeypatch)
    service.write_document("a", job)
    service.write_document("a", job)  # detached job still has old checkpoint zero
    assert len(calls) == 2  # one conversion + one write
    with module.session_scope() as db:
        assert db.get(FeishuDeliveryDB, job.id).written_blocks == "2"
        assert db.get(FeishuWriteBatchDB, (job.id, "0")).state == "confirmed"


def test_unknown_write_never_replays(service, monkeypatch):
    job = job_for(service)
    calls = fake_calls(service, monkeypatch, fail=module.FeishuError("timeout", 502, uncertain=True))
    with pytest.raises(module.FeishuError): service.write_document("a", job)
    with pytest.raises(module.FeishuError): service.write_document("a", job)
    assert len(calls) == 2
    with module.session_scope() as db:
        assert db.get(FeishuWriteBatchDB, (job.id, "0")).state == "unknown"


def test_definite_failure_retries_identical_uuid_and_body(service, monkeypatch):
    job = job_for(service)
    calls = fake_calls(service, monkeypatch, fail=module.FeishuError("rate", 429, code="rate_limited"))
    with pytest.raises(module.FeishuError): service.write_document("a", job)
    second = fake_calls(service, monkeypatch)
    service.write_document("a", job)
    assert calls[-1] == second[0]


def test_changed_frozen_plan_is_refused(service, monkeypatch):
    job = job_for(service)
    fake_calls(service, monkeypatch)
    service.prepare_native_body("a", job)
    with module.session_scope() as db:
        meta = db.get(FeishuDeliveryDestinationDB, job.id)
        data = json.loads(meta.snapshot)
        data["body_plan"]["batches"][0]["body"]["index"] = 8
        meta.snapshot = json.dumps(data)
    with pytest.raises(module.FeishuError, match="原转换计划已变化"):
        service.write_document("a", job)


def test_legacy_keeps_exact_children_algorithm(service, monkeypatch):
    job = job_for(service, "# 主题\n- **确认**\n|A|B|", legacy=True)
    calls = []
    monkeypatch.setattr(service, "request", lambda method, path, **kwargs: calls.append((path, kwargs)) or {})
    service.write_document("a", job)
    assert len(calls) == 1 and calls[0][0].endswith("/children")
    children = calls[0][1]["body"]["children"]
    assert [c["block_type"] for c in children] == [3, 12, 2]
    assert children[-1]["text"]["elements"][0]["text_run"]["content"] == "|A|B|"


def test_owner_cannot_use_other_plan(service, monkeypatch):
    job = job_for(service)
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("no external calls"))
    with pytest.raises(module.HTTPException) as error: service.prepare_native_body("b", job)
    assert error.value.status_code == 404


def test_missing_mapping_is_unknown(service, monkeypatch):
    job = job_for(service)
    monkeypatch.setattr(service, "request", lambda m, p, **k: table_conversion() if p.endswith("convert") else {})
    with pytest.raises(module.FeishuError): service.write_document("a", job)
    with module.session_scope() as db:
        assert db.get(FeishuWriteBatchDB, (job.id, "0")).state == "unknown"


def test_missing_plan_with_prior_write_cannot_reconvert(service, monkeypatch):
    job = job_for(service)
    with module.session_scope() as db:
        receipts.begin_batch(db, "a", job.id, 0, {"legacy": True})
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("no conversion"))
    with pytest.raises(module.FeishuError) as error: service.prepare_native_body("a", job)
    assert error.value.code == "write_unknown"


def test_conversion_permission_failure_creates_no_document(service, monkeypatch):
    job = service.enqueue("a", "new", "title", "|A|B|\n|---|---|\n|x|y|")
    monkeypatch.setattr(service, "assert_delivery_connection", lambda *a: None)
    monkeypatch.setattr(service, "request", lambda *a, **k: (_ for _ in ()).throw(module.FeishuError("scope", 403, code="app_scope_missing")))
    monkeypatch.setattr(service, "create_document", lambda *a: pytest.fail("conversion precedes creation"))
    service.process("a", job["id"])
    assert service.delivery_by_id("a", job["id"])["status"] == "failed"
    with module.session_scope() as db: assert db.get(FeishuDeliveryDB, job["id"]).document_id == ""


def test_official_response_example_table_subtree():
    # Public official example is independent of our hand-built fixture.
    response = json.loads((ROOT / "tests/fixtures/feishu_convert_table.json").read_text(encoding="utf-8"))
    blocks = {b["block_id"]: b for b in response["blocks"]}
    table = next(b for b in blocks.values() if b["block_type"] == 31)
    chosen = []
    def visit(block):
        chosen.append(block)
        for child in block.get("children", []): visit(blocks[child])
    visit(table)
    body = native.prepare_plan("official table", {"first_level_block_ids": [table["block_id"]], "blocks": chosen})["batches"][0]["body"]
    assert len(body["descendants"]) == 13
    assert body["descendants"][0]["table"]["property"]["row_size"] == 2
    assert "merge_info" not in body["descendants"][0]["table"]["property"]


def test_partial_batch_definite_failure_resumes_root_offset(service, monkeypatch):
    converted = {"first_level_block_ids": [f"p{i}" for i in range(1001)],
                 "blocks": [paragraph(f"p{i}") for i in range(1001)]}
    job = job_for(service, "long source")
    calls = fake_calls(service, monkeypatch, converted)
    request = service.request
    def second_fails(m, p, **kwargs):
        if p.endswith("descendant") and kwargs["body"]["index"] == 1000:
            raise module.FeishuError("rate limit", 429)
        return request(m, p, **kwargs)
    monkeypatch.setattr(service, "request", second_fails)
    with pytest.raises(module.FeishuError): service.write_document("a", job)
    with module.session_scope() as db:
        resumed = db.get(FeishuDeliveryDB, job.id)
        assert resumed.written_blocks == "1000"
        db.expunge(resumed)
    again = fake_calls(service, monkeypatch)
    service.write_document("a", resumed)
    assert len(again) == 1 and again[0][1]["body"]["index"] == 1000
    assert len(calls) == 2


def test_conversion_timeout_is_retryable_without_write_marker(service, monkeypatch):
    job = job_for(service)
    monkeypatch.setattr(service, "request", lambda *a, **k: (_ for _ in ()).throw(module.FeishuError("timeout", 502, uncertain=True)))
    with pytest.raises(module.FeishuError) as error: service.prepare_native_body("a", job)
    assert not error.value.uncertain
    with module.session_scope() as db: assert not receipts.has_unknown_batch(db, job.id)
    calls = fake_calls(service, monkeypatch)
    service.write_document("a", job)
    assert len(calls) == 2


def test_nontrivial_merge_cannot_be_silently_discarded():
    data = table_conversion()
    data["blocks"][0]["table"]["property"]["merge_info"][0]["col_span"] = 2
    with pytest.raises(native.FormatError, match="Merged cells"): native.prepare_plan("source", data)


@pytest.mark.parametrize("content", ["普通正文", "# 标题\n- **粗体**\n1. 列表", "a | b"])
def test_simple_and_image_only_need_no_converter(service, monkeypatch, content):
    job = job_for(service, content, selective=True)
    calls = []
    monkeypatch.setattr(service, "granted_scopes", lambda row: set())
    monkeypatch.setattr(service, "request", lambda m, p, **k: calls.append((p, k)) or {})
    service.write_document("a", job)
    assert len(calls) == 1 and calls[0][0].endswith("children")



@pytest.mark.parametrize("content,kind", [
    ("|A|\n|---|\n|x|", "table"),
    ("A | B\n:--- | ---:\nx | y", "table"),
    ("```py\nx = 1\n```", "code"),
    ("~~~\n![literal](x)\n~~~", "code"),
    ("    print(1)\n", "code"),
    ("*斜体*", "inline"), ("`代码`", "inline"),
    ("[链接](https://example.com)", "inline"), ("~~删除~~", "inline")])
def test_needed_converter_classification(content, kind):
    assert kind in native.format_selection(content)["native_required"]


def test_scope_preflight_refuses_only_complex_no_remote_request(service, monkeypatch):
    job = job_for(service, selective=True)
    monkeypatch.setattr(service, "granted_scopes", lambda row: {"docx:document"})
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("preflight must happen before converter"))
    with pytest.raises(module.FeishuError) as error: service.write_document("a", job)
    assert error.value.code == "converter_scope_missing"


def test_table_never_falls_back_to_raw_pipes(service, monkeypatch):
    job = job_for(service, selective=True)
    calls = fake_calls(service, monkeypatch, {"first_level_block_ids": ["raw"], "blocks": [paragraph("raw", "|A|B|")]})
    with pytest.raises(module.FeishuError, match="未生成原生表格"): service.write_document("a", job)
    assert len(calls) == 1 and calls[0][0].endswith("convert")
    with module.session_scope() as db: assert not receipts.has_unknown_batch(db, job.id)


@pytest.mark.parametrize("content", ["![图](attachment://abc)", "普通正文\n![图](x)\n|A|B|\n|---|---|\n|x|y|", "<img src='x'>", "![图][ref]\n[ref]: https://example.com/x"])
def test_images_fail_before_conversion_creation_write_or_message(service, monkeypatch, content):
    data = service.enqueue("a", str(uuid.uuid4()), "title", content)
    monkeypatch.setattr(service, "assert_delivery_connection", lambda *a: None)
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("no remote call"))
    monkeypatch.setattr(service, "create_document", lambda *a: pytest.fail("no document creation"))
    monkeypatch.setattr(service, "send_message", lambda *a: pytest.fail("no message"))
    service.process("a", data["id"])
    receipt = service.delivery_by_id("a", data["id"])
    assert receipt["status"] == "failed"
    assert receipt["phase"] == "failed"
    assert receipt["error_code"] == "format_unsupported"
    assert receipt["formatting"]["status"] == "unsupported"
    with module.session_scope() as db:
        row = db.get(FeishuDeliveryDB, data["id"])
        assert row.document_id == "" and row.written_blocks == "0"
        assert db.get(FeishuWriteBatchDB, (data["id"], "0")) is None


def test_image_inside_table_is_blocked_without_cloud_call(service, monkeypatch):
    job = job_for(service, "|A|B|\n|---|---|\n|![图](x)|y|", selective=True)
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("no external call"))
    with pytest.raises(module.FeishuError) as error: service.write_document("a", job)
    assert error.value.code == "format_unsupported"


def test_inline_conversion_cannot_return_unformatted_source():
    with pytest.raises(native.FormatError, match="行内样式"):
        native.selective_plan("*斜体*", lambda text: {"first_level_block_ids": ["x"], "blocks": [paragraph("x", text)]})


def test_selective_ids_unique_between_conversion_calls():
    content = "*斜体*\nplain\n*另一斜体*"
    plan = native.selective_plan(content, lambda text: {"first_level_block_ids": ["same"], "blocks": [paragraph("same", text, italic=True)]})
    ids = [b["block_id"] for batch in plan["batches"] for b in batch["body"]["descendants"]]
    assert len(ids) == len(set(ids)) == 3


def test_status_exposes_grants_without_claiming_app_permission(service, monkeypatch):
    monkeypatch.setattr(service, "granted_scopes", lambda row: {"docx:document"})
    status = service.status("a")
    assert not status["markdown_conversion_preflight"]["user_grant_available"]
    assert not status["markdown_conversion_preflight"]["app_permission_verified"]
    assert status["capabilities"]["personal"]


def test_selective_frozen_plan_no_reconversion_after_grants_change(service, monkeypatch):
    job = job_for(service, selective=True)
    fake_calls(service, monkeypatch)
    plan = service.prepare_native_body("a", job)
    monkeypatch.setattr(service, "granted_scopes", lambda row: set())
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("no conversion"))
    assert service.prepare_native_body("a", job) == plan




def test_duplicate_operation_cannot_reselect_format(service, monkeypatch):
    first = service.enqueue("a", "dup", "title", "plain", operation_id="same-op")
    monkeypatch.setattr(native, "format_selection", lambda content: pytest.fail("must return original operation before classifying"))
    again = service.enqueue("a", "dup", "title", "plain", operation_id="same-op")
    assert first["id"] == again["id"]


def test_converter_image_block_fails_before_document_creation(service, monkeypatch):
    data = service.enqueue("a", "converter-image", "title", "|A|B|\n|---|---|\n|x|y|")
    monkeypatch.setattr(service, "assert_delivery_connection", lambda *a: None)
    converted = table_conversion()
    converted["blocks"][-1]["block_type"] = 27
    calls = fake_calls(service, monkeypatch, converted)
    monkeypatch.setattr(service, "create_document", lambda *a: pytest.fail("no creation"))
    monkeypatch.setattr(service, "send_message", lambda *a: pytest.fail("no notification"))
    service.process("a", data["id"])
    receipt = service.delivery_by_id("a", data["id"])
    assert receipt["error_code"] == "format_unsupported"
    assert len(calls) == 1 and calls[0][0].endswith("convert")
    with module.session_scope() as db:
        row = db.get(FeishuDeliveryDB, data["id"])
        assert row.document_id == "" and row.written_blocks == "0"
        assert db.get(FeishuWriteBatchDB, (data["id"], "0")) is None


INLINE_SOURCE = "**粗体** *斜体* `代码` ~~删除~~ [链接](https://example.com)"
INLINE_STYLES = {"bold": True, "italic": True, "inline_code": True,
                 "strikethrough": True, "link": {"url": "https%3A%2F%2Fexample.com"}}


@pytest.mark.parametrize("missing", list(INLINE_STYLES))
def test_missing_any_inline_class_stops_before_document_or_write(service, monkeypatch, missing):
    styles = {k: v for k, v in INLINE_STYLES.items() if k != missing}
    data = service.enqueue("a", "missing-" + missing, "title", INLINE_SOURCE)
    calls = fake_calls(service, monkeypatch, {"first_level_block_ids": ["x"], "blocks": [paragraph("x", "正文", **styles)]})
    monkeypatch.setattr(service, "assert_delivery_connection", lambda *a: None)
    monkeypatch.setattr(service, "create_document", lambda *a: pytest.fail("missing style cannot create document"))
    monkeypatch.setattr(service, "send_message", lambda *a: pytest.fail("missing style cannot notify"))
    service.process("a", data["id"])
    assert service.delivery_by_id("a", data["id"])["error_code"] == "format_unsupported"
    assert len(calls) == 1 and calls[0][0].endswith("convert")
    with module.session_scope() as db:
        assert db.get(FeishuDeliveryDB, data["id"]).document_id == ""
        assert db.get(FeishuWriteBatchDB, (data["id"], "0")) is None


def test_all_inline_classes_preserved_across_different_elements():
    blocks = [paragraph(str(i), name, **{name: value}) for i, (name, value) in enumerate(INLINE_STYLES.items())]
    plan = native.selective_plan(INLINE_SOURCE, lambda text: {"first_level_block_ids": [b["block_id"] for b in blocks], "blocks": blocks})
    native.validate_frozen_inline_styles(INLINE_SOURCE, plan)
    assert len(plan["batches"][0]["body"]["descendants"]) == 5


@pytest.mark.parametrize("style", [{"italic": False}, {"italic": "true"}, {"link": {}}, {"link": {"url": ""}}, {"link": {"url": 1}}])
def test_false_or_malformed_style_is_not_retention_evidence(style):
    source = "*斜体*" if "italic" in style else "[链接](https://example.com)"
    with pytest.raises(native.FormatError, match="行内样式"):
        native.validate_inline_styles(source, [paragraph("x", "正文", **style)])


@pytest.mark.parametrize("text,expected", [
    ("`*literal* ~~literal~~ [literal](x)`", {"inline_code"}),
    ("``*literal*``", {"inline_code"}),
    ("\\*literal\\* `code`", {"inline_code"}),
    ("[链接](https://example.com/a_b_c)", {"link"}),
    ("***粗斜体***", {"bold", "italic"}),
    ("__粗体__ _斜体_", {"bold", "italic"}),
])
def test_required_inline_classes_distinguish_literals_and_link_targets(text, expected):
    assert native.required_inline_styles(text) == expected


def test_previous_incomplete_frozen_plan_is_refused_without_reconversion_or_rebinding(service, monkeypatch):
    job = job_for(service, INLINE_SOURCE, selective=True)
    fake_calls(service, monkeypatch, {"first_level_block_ids": ["x"], "blocks": [paragraph("x", "正文", **INLINE_STYLES)]})
    plan = service.prepare_native_body("a", job)
    with module.session_scope() as db:
        metadata = db.get(FeishuDeliveryDestinationDB, job.id)
        snapshot = json.loads(metadata.snapshot)
        del snapshot["body_plan"]["batches"][0]["body"]["descendants"][0]["text"]["elements"][0]["text_run"]["text_element_style"]["link"]
        # Simulate a legitimately frozen older candidate plan, not a hash tamper.
        snapshot["body_plan_hash"] = receipts.fingerprint(snapshot["body_plan"])
        metadata.snapshot = json.dumps(snapshot)
        frozen_snapshot = metadata.snapshot
    monkeypatch.setattr(service, "request", lambda *a, **k: pytest.fail("cannot reconvert/rewrite frozen plan"))
    with pytest.raises(module.FeishuError) as error:
        service.write_document("a", job)
    assert error.value.code == "format_unsupported"
    with module.session_scope() as db:
        assert db.get(FeishuDeliveryDestinationDB, job.id).snapshot == frozen_snapshot
        assert db.get(FeishuWriteBatchDB, (job.id, "0")) is None
