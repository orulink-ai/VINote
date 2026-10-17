"""Generation fencing tests. No providers; run serially with the workspace suite.

The few two-thread cases use independent SQLite sessions and bypass only the
process-local capacity semaphore, reproducing separate workers sharing one DB.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models.workspace import GenerateVersion, PutNote, SharedVersion, WorkspaceGenerationDB, WorkspaceVersionDB
from app.models.workspace_generation_claim import WorkspaceGenerationClaimDB
from app.services import workspace_generation as module
from app.services import workspace_service


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}",
                           connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db, db.begin():
            yield db

    monkeypatch.setattr(module, "session_scope", sessions)
    monkeypatch.setattr(workspace_service, "session_scope", sessions)
    state = SimpleNamespace(clock=datetime.now(timezone.utc), calls=0, behavior=None)
    monkeypatch.setattr(module, "now", lambda: state.clock)
    count_lock = threading.Lock()

    class Model:
        model = "fake-model"

        def summarize(self, *args, **kwargs):
            with count_lock:
                state.calls += 1
                call = state.calls
            return state.behavior(call) if state.behavior else "生成结果"

    @contextmanager
    def fake_summarizer(*args, **kwargs):
        yield Model()

    monkeypatch.setattr(module, "summarizer", fake_summarizer)
    state.sessions = sessions
    state.workspace = workspace_service.WorkspaceService()
    state.worker = module.WorkspaceGeneration()
    state.worker.workspace = state.workspace
    state.seed = lambda owner="a", key="note": state.workspace.put(owner, key,
        PutNote(operation_id="seed", base_revision=0, title="会议", content="原文"))
    state.seed()
    yield state
    engine.dispose()


def request(**kwargs):
    return GenerateVersion(base_revision=1, operation_id="generate", **kwargs)


def generation_id(owner="a", key="note", payload=None):
    return "generated-" + module.digest([owner, key, (payload or request()).operation_id])[:40]


def acquire(env, owner="a", key="note", payload=None, worker=None):
    payload = payload or request()
    worker = worker or env.worker
    return worker._acquire(owner, key, payload, module.digest({"key": key, **payload.model_dump()}),
                           generation_id(owner, key, payload), env.workspace.get(owner, key))


def generate(env, *, worker=None, owner="a", key="note", payload=None):
    return (worker or env.worker)._generate(owner, (owner, "local-user"), key, payload or request(), None)


def stored(env, owner="a", operation_id="generate"):
    with env.sessions() as db:
        job = db.get(WorkspaceGenerationDB, (owner, operation_id))
        claim = db.get(WorkspaceGenerationClaimDB, (owner, operation_id))
        return {"status": job.status, "output": job.output, "error": job.error, "model": job.model,
                "token": claim.execution_token, "lease": claim.lease_until,
                "publication": claim.publication_json}


def freeze(env, token, output="已持久输出"):
    output, model = env.worker._checkpoint_output("a", "generate", token, output, "fake-model")
    gid = generation_id()
    body = PutNote(operation_id=gid, base_revision=1, title="会议", content=output,
                   versions=[SharedVersion(id=gid, title="会议", content=output,
                                           kind="generated", model=model, created_at=env.clock)])
    return env.worker._publication("a", "generate", token, body)


@pytest.mark.parametrize("retry", [False, True])
def test_database_claim_allows_only_one_worker_for_create_or_retry(env, retry):
    if retry:
        token, _, _ = acquire(env)
        env.worker._finish("a", "generate", token, generation_id(), succeeded=False, error="retryable")
    start = threading.Barrier(2)

    def contender():
        worker = module.WorkspaceGeneration()
        start.wait(timeout=5)
        try:
            return acquire(env, worker=worker)
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(contender), pool.submit(contender)
        results = [first.result(timeout=10), second.result(timeout=10)]
    successes = [result for result in results if not isinstance(result, HTTPException)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == len(failures) == 1
    assert failures[0].status_code == 409
    assert stored(env)["token"] == successes[0][0]
    with env.sessions() as db:
        assert db.scalar(select(func.count()).select_from(WorkspaceGenerationDB)) == 1
        assert db.scalar(select(func.count()).select_from(WorkspaceGenerationClaimDB)) == 1


@pytest.mark.parametrize("old_fails", [False, True])
def test_late_worker_cannot_overwrite_success_after_takeover(env, old_fails):
    entered, release = threading.Event(), threading.Event()

    def behavior(call):
        if call == 1:
            entered.set()
            assert release.wait(timeout=10)
            if old_fails:
                raise RuntimeError("late provider failure")
            return "迟到旧结果"
        return "接管者已完成结果"

    env.behavior = behavior
    old_worker = module.WorkspaceGeneration()
    with ThreadPoolExecutor(max_workers=1) as pool:
        late = pool.submit(generate, env, worker=old_worker)
        try:
            assert entered.wait(timeout=5)
            old_token = stored(env)["token"]
            env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
            winner = generate(env)
            assert winner["content"] == "接管者已完成结果"
            assert stored(env)["status"] == "completed"
        finally:
            release.set()
        with pytest.raises(HTTPException) as caught:
            late.result(timeout=5)
    assert caught.value.status_code == (502 if old_fails else 409)
    state = stored(env)
    assert state["status"] == "completed"
    assert state["output"] == "接管者已完成结果"
    assert state["error"] == ""
    assert state["token"] == ""
    assert env.worker._finish("a", "generate", old_token, generation_id(), succeeded=False, error="late") is False
    with env.sessions() as db:
        versions = list(db.scalars(select(WorkspaceVersionDB).where(WorkspaceVersionDB.kind == "generated")))
        assert len(versions) == 1
        assert versions[0].content == "接管者已完成结果"
    assert env.workspace.get("a", "note")["content"] == "接管者已完成结果"


def test_expiration_revokes_token_but_preserves_checkpoint(env):
    token, _, _ = acquire(env)
    frozen = freeze(env, token)
    publication = stored(env)["publication"]
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    assert env.worker.jobs("a")[0]["status"] == "failed"
    assert stored(env)["output"] == frozen.content
    assert stored(env)["publication"] == publication
    assert stored(env)["token"] == ""
    with pytest.raises(HTTPException) as caught:
        env.worker._checkpoint_output("a", "generate", token, "旧线程篡改", "old-model")
    assert caught.value.detail["code"] == "GENERATION_CLAIM_LOST"
    result = generate(env)
    assert result["content"] == "已持久输出"
    assert env.calls == 0
    assert stored(env)["publication"] == publication
    assert stored(env)["status"] == "completed"


def test_output_and_publication_remain_fixed_after_save_failure(env, monkeypatch):
    real_put = env.workspace.put
    submissions = []

    def flaky_put(owner, key, body, **kwargs):
        submissions.append((body.model_dump(mode="json", exclude_unset=True), kwargs))
        if len(submissions) == 1:
            raise RuntimeError("temporary DB outage before save")
        return real_put(owner, key, body, **kwargs)

    monkeypatch.setattr(env.workspace, "put", flaky_put)
    with pytest.raises(HTTPException):
        generate(env)
    failed = stored(env)
    assert failed["status"] == "failed"
    assert failed["output"] == "生成结果"
    assert failed["publication"]
    env.clock += timedelta(seconds=30)
    result = generate(env)
    assert result["content"] == "生成结果"
    assert submissions[0] == submissions[1]
    assert submissions[1][1] == {"version_evidence": {generation_id(): 1}}
    assert env.calls == 1
    assert stored(env)["status"] == "completed"


def test_save_committed_but_reply_lost_recovers_without_generation(env, monkeypatch):
    real_put = env.workspace.put

    def lost_reply(owner, key, body, **kwargs):
        real_put(owner, key, body, **kwargs)
        raise RuntimeError("reply was lost after commit")

    monkeypatch.setattr(env.workspace, "put", lost_reply)
    with pytest.raises(HTTPException):
        generate(env)
    assert stored(env)["status"] == "completed"
    assert stored(env)["error"] == ""
    first = env.workspace.get("a", "note")
    replay = generate(env)
    assert replay["revision"] == first["revision"]
    assert replay["version_count"] == first["version_count"]
    assert env.calls == 1


def test_process_exit_after_publication_reuses_saved_output(env, monkeypatch):
    class ProcessExit(BaseException):
        pass

    real_put = env.workspace.put

    def crash(*args, **kwargs):
        raise ProcessExit()

    monkeypatch.setattr(env.workspace, "put", crash)
    with pytest.raises(ProcessExit):
        generate(env)
    before = stored(env)
    assert before["status"] == "running"
    assert before["publication"]
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    monkeypatch.setattr(env.workspace, "put", real_put)
    result = generate(env)
    assert result["content"] == before["output"]
    assert stored(env)["publication"] == before["publication"]
    assert stored(env)["status"] == "completed"
    assert env.calls == 1


def test_late_publisher_can_only_replay_immutable_body(env):
    old_token, _, _ = acquire(env)
    old_body = freeze(env, old_token)
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    winner = generate(env)
    # Old worker paused after obtaining its publication but before workspace.put.
    # Its payload is exactly the winner's, so this cannot create or replace a version.
    late = env.workspace.put("a", "note", old_body, version_evidence={generation_id(): 1})
    assert late["revision"] == winner["revision"]
    assert late["version_count"] == winner["version_count"]
    assert env.worker._finish("a", "generate", old_token, generation_id(), succeeded=True) is False
    assert stored(env)["status"] == "completed"
    assert stored(env)["output"] == "已持久输出"


def test_stale_jobs_poll_cannot_downgrade_completed_generation(env, monkeypatch):
    token, _, _ = acquire(env)
    body = freeze(env, token)
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    expire = env.worker._expire

    def complete_after_ids_selected(owner, operation_id):
        env.workspace.put(owner, "note", body, version_evidence={generation_id(): 1})
        env.worker._finish(owner, operation_id, token, generation_id(), succeeded=True)
        expire(owner, operation_id)

    monkeypatch.setattr(env.worker, "_expire", complete_after_ids_selected)
    result = env.worker.jobs("a")
    assert result[0]["status"] == "completed"
    assert stored(env)["error"] == ""


def test_checkpoint_renews_claim_and_poll_uses_lease_not_old_job_timestamp(env):
    token, _, _ = acquire(env)
    env.clock += timedelta(seconds=module.CLAIM_SECONDS - 1)
    env.worker._checkpoint_output("a", "generate", token, "checkpoint", "model")
    env.clock += timedelta(seconds=2)
    assert env.worker.jobs("a")[0]["status"] == "running"
    assert stored(env)["token"] == token


def test_claim_owner_and_payload_binding(env):
    token, _, _ = acquire(env)
    with pytest.raises(HTTPException):
        acquire(env, payload=request(instructions="different input"))
    with pytest.raises(HTTPException):
        env.worker._checkpoint_output("other", "generate", token, "cross-owner", "model")
    env.seed(owner="other")
    other, _, _ = acquire(env, owner="other")
    assert other != token
    assert env.worker.jobs("unknown") == []
    env.worker._checkpoint_output("other", "generate", other, "other owner result", "model")
    assert stored(env)["output"] == ""
    assert stored(env, "other")["output"] == "other owner result"


def test_fresh_legacy_running_job_is_not_immediately_stolen(env):
    payload = request()
    with env.sessions() as db:
        db.add(WorkspaceGenerationDB(owner="a", operation_id=payload.operation_id, note_key="note",
            digest=module.digest({"key": "note", **payload.model_dump()}), base_revision=1,
            status="running", updated_at=env.clock))
    for _ in range(2):
        with pytest.raises(HTTPException) as caught:
            generate(env)
        assert caught.value.status_code == 409
    assert env.calls == 0
    with env.sessions() as db:
        assert db.get(WorkspaceGenerationClaimDB, ("a", "generate")) is None
    assert env.worker.jobs("a")[0]["status"] == "running"
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    assert generate(env)["content"] == "生成结果"
    assert env.calls == 1


def test_expired_original_token_is_fenced_after_takeover_without_output(env):
    old, _, _ = acquire(env)
    env.clock += timedelta(seconds=module.CLAIM_SECONDS + 1)
    current, _, _ = acquire(env)
    assert current != old
    with pytest.raises(HTTPException):
        env.worker._checkpoint_output("a", "generate", old, "late", "old")
    assert env.worker._finish("a", "generate", old, generation_id(), succeeded=False, error="late") is False
    state = stored(env)
    assert state["status"] == "running"
    assert state["token"] == current
    assert state["output"] == ""


@pytest.mark.parametrize("source_type", ["file", "text", "audio", "video", "meeting_recording", "meeting_video"])
@pytest.mark.parametrize("template", ["minutes", "summary", "actions"])
def test_generation_template_respects_source_and_preserves_history(env, monkeypatch, source_type, template):
    """PDF/Word/web are file/text; audio/video and a meeting title are not meetings.

    Exercise actual generation, prompt construction and publication, including a
    lost-response retry. The provider alone is replaced; no real LLM is called.
    """
    from app.llm.prompts import build_user_prompt

    title, original = "会议方法研究资料", "第一节：已有论点。\n第二节：明确步骤与结论。"
    key = "source-contract"
    source = env.workspace.put("a", key, PutNote(operation_id="source-seed", base_revision=0,
        title=title, content=original, source_type=source_type,
        versions=[SharedVersion(id="original", title=title, content=original,
                                kind="imported", created_at=env.clock)]))
    seen = []

    class Model:
        model = "fake-model"

        def summarize(self, actual_title, segments, **options):
            text = "\n".join(segment.text for segment in segments)
            seen.append({"options": options, "text": text,
                         "prompt": build_user_prompt(actual_title, text, style=options["style"],
                             extras=options["extras"], output_language=options["output_language"])})
            return "# 已整理\n" + original

    @contextmanager
    def provider(*args, **kwargs):
        yield Model()

    monkeypatch.setattr(module, "summarizer", provider)
    payload = GenerateVersion(operation_id="source-generate", base_revision=source["revision"], template=template)
    result = env.worker.generate(("a", "local-user"), key, payload)
    meeting = source_type in ("meeting_recording", "meeting_video")
    expected_goal = {"minutes": "完整会议纪要" if meeting else "完整结构化笔记",
                     "summary": "简短总结", "actions": "仅列明确的行动事项，不编造负责人和期限"}[template]
    assert len(seen) == 1 and seen[0]["text"] == original
    assert json.loads(seen[0]["options"]["extras"])["用户整理目标"] == expected_goal
    assert seen[0]["options"]["style"] == ("meeting" if meeting else "detailed")
    assert expected_goal in seen[0]["prompt"]
    if not meeting:
        assert "完整会议纪要" not in seen[0]["prompt"]
    assert seen[0]["options"]["summary_mode"] == "default"
    assert result["source_type"] == source_type and result["revision"] > source["revision"]
    assert result["version_count"] > source["version_count"]
    assert {version["id"] for version in source["versions"]} <= {version["id"] for version in result["versions"]}
    assert next(version for version in result["versions"] if version["id"] == "original")["content"] == original
    generated = [version for version in result["versions"] if version["kind"] == "generated"]
    assert len(generated) == 1 and generated[0]["content"] == result["content"]
    replay = env.worker.generate(("a", "local-user"), key, payload)
    assert len(seen) == 1 and replay["revision"] == result["revision"]
    assert replay["version_count"] == result["version_count"]
    assert {version["id"] for version in replay["versions"]} == {version["id"] for version in result["versions"]}
