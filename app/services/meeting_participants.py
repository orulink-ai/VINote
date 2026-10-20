"""Attendance candidates and explicit task-scoped human confirmations.

Integration: resolve_saved_meeting(service, owner, note_key, title=..., content=...).
The caller owns notify_participants consent, publication and frozen receipts.
Neither raw artifact fields nor the generated note can authorize a recipient.

Current artifacts have no authenticated name-to-speaker association. Even a
self-introduction is therefore a review candidate, never an automatic recipient.
Temporal overlap, estimated labels, visual prose and repeated mentions cannot
upgrade that conclusion. Only the explicit confirmation mutation saves attendance
assertions. Short-lived selection tokens are validated, never stored. Resolution
obtains fresh exact-ID selection proofs, never sends or infers. It requires no
employment/status API or employee permission.
Evidence revisions are opaque hashes, not authority tokens.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import unicodedata
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.db_models import NoteDB, SourceRequestDB
from app.models.meeting_participants import MeetingParticipantConfirmationDB as Confirmation
from app.models.transcript import TranscriptSegment
from app.services import feishu_object_hotwords
from app.services.meeting_evidence import original_asr_evidence
from app.services.task_artifact_service import TaskArtifactService

_MAX_BYTES = 8 * 1024 * 1024
_MAX_TEXT = 600000
_MAX_CANDIDATES = 200
_FILES = ("transcript.json", "speaker_evidence.json", "visual_observations.json")
_IDENTITY_FILES = ("recording_owner", ".task_id", "request.json", "status.json")


def _key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _unresolved(reason, candidate=None):
    return {"reason": reason, **({"candidate_id": candidate} if candidate else {})}


def _terms(snapshot):
    """Exact names/explicit aliases only, including ambiguous names as such."""
    objects = snapshot.get("objects", [])
    aliases = snapshot.get("aliases", [])
    if not isinstance(objects, list) or not isinstance(aliases, list) or len(objects) > 5000 or len(aliases) > 200:
        raise ValueError("hotwords_invalid")
    contacts = {item["id"]: item for item in objects if isinstance(item, dict)
                and item.get("kind") == "contact" and isinstance(item.get("id"), str)
                and re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", item["id"])
                and isinstance(item.get("name"), str)}
    terms = {}
    for item in contacts.values():
        name = _key(item["name"])
        if 0 < len(name) <= 500:
            terms.setdefault(name, set()).add(item["id"])
    for alias in aliases:
        if (isinstance(alias, dict) and alias.get("target_id") in contacts
                and isinstance(alias.get("alias"), str)):
            name = _key(alias["alias"])
            if 0 < len(name) <= 50:
                terms.setdefault(name, set()).add(alias["target_id"])
    return terms, contacts


def _role(text, name, visual):
    if visual:
        return "visual_name", "visual_prose_not_attendance"
    escaped = re.escape(name)
    # Narrow descriptions aid review only. Quotes, negation, recordings and
    # instructions may contain identical phrases; no rule here grants identity.
    if re.search(r"(?:^|[。！？；\n])\s*(?:大家好[，,、]?\s*)?(?:我叫|我是)\s*" + escaped + r"(?:[，,。！!；;\s]|$)", text):
        return "self_introduction", "speaker_identity_unverified"
    if re.search(r"(?:今天|本次|此次)?(?:实际)?(?:参会人员|参会者|出席人员|到会人员)(?:是|有|为|包括|名单)?\s*[:：]?[^。！？\n]{0,150}" + escaped, text):
        return "attendance_statement", "attendance_statement_unverified"
    if re.search(escaped + r"\s*(?:负责|跟进|来做|完成)", text):
        return "action_owner", "task_ownership_not_attendance"
    return "mention", "mention_not_attendance"


def resolve_attendance(snapshot, evidence):
    """Pure projection of untrusted evidence; never accepts participant lists.

    snapshot: current scoped hotwords snapshot {objects, aliases}.
    evidence: {transcript, speaker, visual}; extra keys (including supplied
    participants, confidence, status and recipient IDs) have no authority.
    Confidence is a reasoned evidence tier rather than a probability.
    """
    result = {"contacts": [], "candidates": [], "unresolved": []}
    if not isinstance(snapshot, dict) or not isinstance(evidence, dict):
        result["unresolved"].append(_unresolved("evidence_invalid"))
        return result
    try:
        terms, _ = _terms(snapshot)
    except ValueError:
        result["unresolved"].append(_unresolved("hotwords_invalid"))
        return result
    materials = []
    transcript = evidence.get("transcript")
    if transcript is not None:
        try:
            original = original_asr_evidence(transcript)
            if len(original["full_text"]) > _MAX_TEXT:
                raise ValueError()
            for index, segment in enumerate(original["segments"]):
                if len(segment["text"]) > _MAX_TEXT:
                    raise ValueError()
                materials.append((segment["text"], {"artifact": "transcript.json", "segment_index": index,
                                  "start": segment["start"], "end": segment["end"]}, False))
            # Full-file text is useful for review when no segments were supplied.
            if not original["segments"] and original["full_text"]:
                materials.append((original["full_text"], {"artifact": "transcript.json"}, False))
        except (ValueError, TypeError, KeyError):
            result["unresolved"].append(_unresolved("transcript_invalid"))
            materials = []
    else:
        result["unresolved"].append(_unresolved("transcript_missing"))
    visual = evidence.get("visual")
    if visual is not None:
        if isinstance(visual, dict) and isinstance(visual.get("text"), str) and len(visual["text"]) <= _MAX_TEXT:
            materials.append((visual["text"], {"artifact": "visual_observations.json"}, True))
        else:
            result["unresolved"].append(_unresolved("visual_invalid"))
    # Speaker turns are deliberately not sentence labels or name mappings.
    transcript_metadata = transcript.get("metadata", {}) if isinstance(transcript, dict) else {}
    if (evidence.get("speaker") is not None
            or isinstance(transcript_metadata, dict) and "speaker_evidence" in transcript_metadata):
        result["unresolved"].append(_unresolved("speaker_intervals_not_identity"))
    found = {}
    # Bound work independently of caller-controlled segment/name multiplicity.
    if sum(len(text) for text, _, _ in materials) > _MAX_TEXT:
        result["unresolved"].append(_unresolved("evidence_budget_exceeded"))
        return result
    if not terms:
        result["unresolved"].append(_unresolved("hotwords_no_contacts"))
        return result
    if sum(map(len, terms)) > 100000:
        result["unresolved"].append(_unresolved("hotwords_budget_exceeded"))
        return result
    matcher = re.compile("|".join(re.escape(term) for term in sorted(terms, key=lambda term: (-len(term), term))))
    budget_exhausted = False
    for text, reference, is_visual in materials:
        normalized = _key(text)
        for match in matcher.finditer(normalized):
            name = match.group()
            ids = terms[name]
            # Lexical matching never uses fuzzy/pinyin/face/voice similarity.
            before = normalized[max(0, match.start() - 12):match.start()]
            after = normalized[match.end():match.end() + 8]
            if (before and re.match(r"\w", before[-1])
                    and not before.endswith(("我是", "我叫", "由", "请", "给", "和", "与", "及", "谈到了", "提到", "提到了",
                                             "参会人员有", "参会者有", "出席人员有", "参会人员是", "参会者是", "参会人员包括"))):
                continue
            if (after and re.match(r"\w", after[0])
                    and not after.startswith(("负责", "跟进", "来做", "完成", "参加", "参会", "说"))):
                continue
            role, reason = _role(normalized[max(0, match.start() - 160):match.end() + 160], name, is_visual)
            candidate_id = _revision({"term": name, "ids": sorted(ids)})
            if candidate_id not in found:
                if len(found) >= _MAX_CANDIDATES:
                    result["unresolved"].append(_unresolved("candidate_budget_exceeded"))
                    budget_exhausted = True
                    break
                found[candidate_id] = {"candidate_id": candidate_id, "name": name,
                    "id": next(iter(ids)) if len(ids) == 1 else None,
                    "matched_ids": sorted(ids), "status": "context_only",
                    "confidence": {"level": "context_only", "reasons": []}, "evidence": []}
            candidate = found[candidate_id]
            if role in {"self_introduction", "attendance_statement"}:
                candidate["status"] = "needs_confirmation"
                candidate["confidence"]["level"] = "attendance_claim_unverified"
            reasons = candidate["confidence"]["reasons"]
            for item in (reason, "name_collision" if len(ids) > 1 else "exact_hotword_match_only"):
                if item not in reasons:
                    reasons.append(item)
            # References and a small excerpt only, never full private artifacts.
            if len(candidate["evidence"]) < 8:
                position = match.start()
                candidate["evidence"].append({**reference, "role": role,
                    "excerpt": normalized[max(0, position - 40):position + len(name) + 60]})
        if budget_exhausted:
            break
    result["candidates"] = list(found.values())
    for item in result["candidates"]:
        result["unresolved"].append(_unresolved("attendance_identity_unverified", item["candidate_id"]))
    result["unresolved"].append(_unresolved("no_verified_attendance_identity"))
    return result


def _read(folder, filename, *, optional=False):
    path = folder / filename
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError("artifact_missing") from None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or getattr(path, "is_junction", lambda: False)()
            or not path.resolve().is_relative_to(folder.resolve()) or info.st_size > _MAX_BYTES):
        raise ValueError("artifact_invalid")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)):
            raise ValueError("artifact_changed")
        value = stream.read(_MAX_BYTES + 1)
        final = os.fstat(stream.fileno())
        if (final.st_size, final.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise ValueError("artifact_changed")
    if len(value) > _MAX_BYTES:
        raise ValueError("artifact_budget_exceeded")
    return value


def _note(owner, note_key, title, content):
    with session_scope() as db:
        row = db.get(NoteDB, note_key)
        if row is None or row.created_by != owner:
            raise HTTPException(404, "未找到当前账号的会议笔记")
        if row.title != title or row.content != content:
            raise HTTPException(409, "笔记已变化，请重新准备本次交付")
        if (row.scope != "personal" or row.status != "done" or row.generation_client != "desktop"
                or row.source_type not in {"meeting_recording", "meeting_video"}):
            raise HTTPException(409, "此笔记不支持自动参会人解析")
        try:
            if str(uuid.UUID(row.task_id)) != row.task_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(409, "会议任务来源无法核验") from None
        return row.task_id


def _context(service, owner, note_key, *, title, content):
    task_id = _note(owner, note_key, title, content)
    artifacts = TaskArtifactService()
    folder = artifacts.find_task_dir(task_id)
    evidence, hashes, failures = {}, {}, []
    canonical, source_hash = None, None
    try:
        if folder is None:
            raise ValueError("task_missing")
        folder = Path(folder)
        root = Path(artifacts.output_dir).resolve()
        if (folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
                or not folder.resolve().is_relative_to(root)):
            raise ValueError("task_invalid")
        identity = {name: _read(folder, name) for name in _IDENTITY_FILES}
        if (identity["recording_owner"].decode("utf-8") != owner
                or identity[".task_id"].decode("utf-8") != task_id):
            raise ValueError("task_identity_mismatch")
        if (json.loads(identity["request.json"]).get("request", {}).get("workflow") != "meeting"
                or json.loads(identity["status.json"]).get("status") != "success"):
            raise ValueError("meeting_completion_unverified")
        # These gate the selected saved version, but do not define attendance.
        canonical, folder, source_hash, visual_revision, canonical_folder = _canonical_meeting(artifacts, owner, task_id)
        evidence_files = (*_FILES, "asr_evidence.json", "video_evidence.json")
        loaded_raw, file_sources = {}, {}
        for filename in evidence_files:
            origin = folder
            raw = _read(origin, filename, optional=True)
            if filename == "visual_observations.json" and raw is None and canonical_folder != folder:
                origin = canonical_folder
                raw = _read(origin, filename, optional=True)
            file_sources[filename] = origin
            loaded_raw[filename] = raw
            hashes[filename] = hashlib.sha256(raw).hexdigest() if raw is not None else None
        from app.services.meeting_summary_regeneration import _evidence
        transcript, _ = _evidence(folder)
        # Use the same complete raw leaf as summary regeneration, including a
        # standalone asr_evidence.json. Estimated wrappers are not new evidence.
        saved = json.loads(loaded_raw["transcript.json"] if loaded_raw["transcript.json"] is not None
                           else loaded_raw["asr_evidence.json"])
        original = original_asr_evidence(transcript.metadata.get("asr_evidence") or saved)
        evidence["transcript"] = original
        speaker = transcript.metadata.get("speaker_evidence")
        if speaker is not None:
            evidence["speaker"] = speaker
        if loaded_raw["visual_observations.json"] is not None:
            visual = json.loads(loaded_raw["visual_observations.json"])
            if not isinstance(visual, dict) or not isinstance(visual.get("text"), str):
                raise ValueError("visual_invalid")
            evidence["visual"] = visual
        # Reject source changes during this read, including optional appearance.
        for filename in evidence_files:
            raw = _read(file_sources[filename], filename, optional=True)
            digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
            if digest != hashes[filename]:
                raise ValueError("artifacts_changed")
        # Commit source facts, not wrapper serialization or a retained manifest's
        # task/path identity. Identical inherited evidence shares attendance;
        # different raw windows, speaker turns or JPEG/OCR facts invalidate it.
        raw_facts = {"language": original.get("language"), "full_text": original["full_text"],
                     "segments": [asdict(TranscriptSegment(**item)) for item in original["segments"]],
                     "metadata": original.get("metadata") or {}}
        hashes = {"raw_asr": _revision(raw_facts), "speaker": _revision(speaker),
                  "visual_observations": _revision(evidence.get("visual")),
                  "verified_visual_frames": visual_revision}
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError, RecursionError, HTTPException):
        evidence = {}
        failures.append(_unresolved("owned_artifacts_unavailable"))
    binding = service.contact_binding(owner)
    snapshot = feishu_object_hotwords.service.snapshot(owner, binding)
    result = resolve_attendance(snapshot, evidence)
    result["unresolved"].extend(failures)
    if service.contact_binding(owner) != binding or _note(owner, note_key, title, content) != task_id:
        raise HTTPException(409, "会议或飞书连接已变化，请重新准备")
    result["canonical_task_id"] = canonical
    result["evidence_revision"] = _revision({"protocol": 3, "owner": owner,
        "canonical_task_id": canonical, "source_sha256": source_hash,
        "artifacts": hashes, "binding": binding})
    valid = (not failures and "transcript" in evidence
             and not any(item["reason"] in {"transcript_invalid", "transcript_missing", "evidence_budget_exceeded"}
                         for item in result["unresolved"]))
    return result, task_id, binding, valid


def _owned_folder(artifacts, owner, task):
    if str(uuid.UUID(task)) != task:
        raise ValueError("invalid_task")
    folder = artifacts.find_task_dir(task)
    if (folder is None or folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
            or folder.resolve().parent != Path(artifacts.output_dir).resolve()
            or _read(folder, "recording_owner").decode() != owner
            or _read(folder, ".task_id").decode() != task
            or (folder / "recording_deleted").exists()
            or json.loads(_read(folder, "request.json")).get("request", {}).get("workflow") != "meeting"):
        raise ValueError("meeting_identity_unverified")
    return folder


def _canonical_meeting(artifacts, owner, task):
    """Verified original identity, with this accepted summary's direct parent.

    Follow bounded DB-fingerprinted summary ancestry, NOT media-reference chains.
    Every media reference must point directly to the same verified original.
    Ancestry establishes identity only. Evidence comes from the selected direct
    parent (or this task for a non-summary), never a search through ancestors.
    Missing/corrupt selected evidence cannot fall back to an older ASR cache.
    """
    from app.services.meeting_summary_regeneration import SummaryConfirmation, _submission
    from app.services.source_request_service import SourceRequestService, _fingerprint
    from app.services.task_original_service import TaskOriginalService
    from app.services.summary_visual_evidence import retained_visual_evidence, visual_version

    references, seen = [], set()
    current, selected_parent = task, None
    for _ in range(9):
        if current in seen:
            raise ValueError("cyclic_summary_ancestry")
        seen.add(current)
        folder = _owned_folder(artifacts, owner, current)
        raw = _read(folder, "source_reference.json", optional=True)
        if raw is None:
            if _read(folder, "new_generation.json", optional=True) is not None:
                raise ValueError("unsupported_evidence_origin")
            canonical = current
            break
        reference = json.loads(raw)
        link = json.loads(_read(folder, "new_generation.json"))
        if link.get("contract") != "meeting-summary-only-v1":
            from app.services.parent_asr_prefix import _submission as independent_submission
            if _read(folder, "new_generation_started").decode() != "claimed":
                raise ValueError("asr_origin_unverified")
            fingerprint = _fingerprint(independent_submission(link))
            with session_scope() as db:
                accepted = db.get(SourceRequestDB, (owner, link["operation_id"]))
                if (accepted is None or accepted.state != "accepted" or accepted.task_id != current
                        or accepted.fingerprint != fingerprint):
                    raise ValueError("asr_receipt_unverified")
            canonical = link.get("canonical_task_id", link["parent_task_id"])
            references.append((reference, link["source_version"]))
            folder = _owned_folder(artifacts, owner, canonical)
            if (_read(folder, "source_reference.json", optional=True) is not None
                    or _read(folder, "new_generation.json", optional=True) is not None):
                raise ValueError("canonical_reference_chain")
            break
        if _read(folder, "summary_generation_started").decode() != "claimed":
            raise ValueError("summary_origin_unverified")
        body = SummaryConfirmation(**{key: link[key] for key in SummaryConfirmation.model_fields if key in link})
        fingerprint = _fingerprint(_submission(link["parent_task_id"], body))
        with session_scope() as db:
            accepted = db.get(SourceRequestDB, (owner, str(body.operation_id)))
            if (accepted is None or accepted.state != "accepted" or accepted.task_id != current
                    or accepted.fingerprint != fingerprint):
                raise ValueError("summary_receipt_unverified")
        references.append((reference, body.source_version))
        if selected_parent is None:
            selected_parent = link["parent_task_id"]
        current = link["parent_task_id"]
    else:
        raise ValueError("summary_ancestry_budget_exceeded")
    info, source = TaskOriginalService().get(owner, "task:" + canonical)
    source_hash = artifacts._sha256(source)
    manifest = json.loads(_read(folder, "source_media.json"))
    if info["task_id"] != canonical or manifest.get("sha256") != source_hash:
        raise ValueError("original_changed")
    expected = {"version": 1, "owner": owner, "parent_task_id": canonical, "source_version": source_hash}
    if any(reference != expected or version != source_hash for reference, version in references):
        raise ValueError("canonical_reference_mismatch")
    evidence_folder = _owned_folder(artifacts, owner, selected_parent or task)
    # Existing evidence validators are read-only; no model/current preference gate.
    # This is exactly summary regeneration's selected-parent/original lookup:
    # a present invalid selected manifest fails, without trying another donor.
    visual = retained_visual_evidence(artifacts, evidence_folder, canonical, source, owner,
        receipts=SourceRequestService(session_scope))
    visual_revision = visual_version(visual)  # Actual retained JPEG digests.
    return canonical, evidence_folder, source_hash, visual_revision, folder


def _saved_body(owner, note_key):
    with session_scope() as db:
        row = db.get(NoteDB, note_key)
        if row is None or row.created_by != owner:
            raise HTTPException(404, "未找到当前账号的会议笔记")
        return row.title, row.content


def _stored(owner, task_id, binding):
    if task_id is None:
        return None
    with session_scope() as db:
        row = db.get(Confirmation, (owner, task_id, feishu_object_hotwords.binding_hash(binding)))
        if row is None:
            return None
        return {"revision": row.revision, "note_key": row.note_key,
                "evidence_revision": row.evidence_revision, "participants": json.loads(row.participants_json),
                "confirmed_at": row.confirmed_at}


def _view(result, task_id, note_key, stored, valid):
    current = bool(valid and stored and stored["evidence_revision"] == result["evidence_revision"])
    return {**result, "task_id": task_id, "note_key": note_key,
            "confirmation": {"revision": stored["revision"] if stored else 0,
                             "status": ("confirmed" if stored["participants"] else "cleared") if current
                                       else "stale" if stored else "unconfirmed",
                             "participants": stored["participants"] if current else [],
                             "confirmed_at": stored["confirmed_at"] if current else None},
            "can_confirm": valid}


def get_meeting_participants(service, owner, note_key):
    """UI read: no contact search, inference, mutation or proof minting."""
    title, content = _saved_body(owner, note_key)
    result, task_id, binding, valid = _context(service, owner, note_key, title=title, content=content)
    return _view(result, task_id, note_key, _stored(owner, result["canonical_task_id"], binding), valid)


def _assert_binding(service, owner, binding):
    if binding.get("owner") != owner or service.contact_binding(owner) != binding:
        raise HTTPException(409, "飞书连接已变化，请重新确认本会议参会人")


def _validated(service, owner, binding, selections):
    """Existing 15-minute ContactSelection with exact ID and current binding."""
    _assert_binding(service, owner, binding)
    proofs = service.validate_contacts(owner, selections)
    expected = {item["open_id"] for item in selections}
    if (not isinstance(proofs, list) or len(proofs) != len(expected)
            or {item.get("open_id") for item in proofs if isinstance(item, dict)} != expected):
        raise HTTPException(409, "联系人选择核验不完整，请重新选择")
    for proof in proofs:
        if (proof.get("purpose") != "feishu_contact_selection_v1"
                or any(proof.get(key) != value for key, value in binding.items())
                or not isinstance(proof.get("name"), str) or not proof["name"].strip()
                or len(proof["name"]) > 500):
            raise HTTPException(409, "联系人选择与本次会议连接不匹配")
    _assert_binding(service, owner, binding)
    return proofs


def confirm_meeting_participants(service, owner, note_key, *, confirmed, task_id,
                                 evidence_revision, confirmation_revision, contacts):
    """Replace this meeting's attendance assertion, never dispatch a delivery.

    Empty contacts explicitly revokes the list. CAS revisions prevent concurrent
    UI saves from restoring removed people. No short-lived token is persisted.
    """
    if (confirmed is not True or type(confirmation_revision) is not int or confirmation_revision < 0
            or not isinstance(contacts, list) or len(contacts) > 20
            or not isinstance(evidence_revision, str) or not re.fullmatch(r"[a-f0-9]{64}", evidence_revision)):
        raise HTTPException(422, "请明确确认本会议实际参会人和当前证据版本")
    for contact in contacts:
        if (not isinstance(contact, dict) or set(contact) != {"open_id", "selection_token"}
                or not isinstance(contact["open_id"], str)
                or not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,196}", contact["open_id"])
                or not isinstance(contact["selection_token"], str) or not 1 <= len(contact["selection_token"]) <= 4096):
            raise HTTPException(422, "请通过现有联系人选择器选择真实参会人")
    if len({item["open_id"] for item in contacts}) != len(contacts):
        raise HTTPException(422, "参会人选择重复")
    title, content = _saved_body(owner, note_key)
    result, actual_task, binding, valid = _context(service, owner, note_key, title=title, content=content)
    if not valid or actual_task != task_id or result["evidence_revision"] != evidence_revision:
        raise HTTPException(409, "会议材料已变化或不可核验，请重新读取后确认")
    canonical = result["canonical_task_id"]
    if canonical is None:
        raise HTTPException(409, "会议来源无法核验，未保存参会人确认")
    previous = _stored(owner, canonical, binding)
    if (previous["revision"] if previous else 0) != confirmation_revision:
        raise HTTPException(409, "本会议参会人确认已变化，请重新读取")
    proofs = _validated(service, owner, binding, contacts) if contacts else []
    fresh, fresh_task, fresh_binding, fresh_valid = _context(service, owner, note_key, title=title, content=content)
    if (not fresh_valid or fresh_task != task_id or fresh_binding != binding
            or fresh["evidence_revision"] != evidence_revision):
        raise HTTPException(409, "会议或连接已变化，未保存参会人确认")
    participants = sorted([{"open_id": p["open_id"], "name": p["name"]} for p in proofs], key=lambda p: p["open_id"])
    try:
        with session_scope() as db:
            if db.get_bind().dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            # Lock the source note as well as the confirmation during the save.
            note = db.scalar(select(NoteDB).where(NoteDB.id == note_key).with_for_update())
            if (note is None or note.created_by != owner or note.task_id != task_id
                    or note.title != title or note.content != content or note.scope != "personal"
                    or note.status != "done" or note.generation_client != "desktop"
                    or note.source_type not in {"meeting_recording", "meeting_video"}):
                raise HTTPException(409, "会议已变化，未保存参会人确认")
            fingerprint = feishu_object_hotwords.binding_hash(binding)
            row = db.scalar(select(Confirmation).where(Confirmation.owner == owner,
                Confirmation.task_id == canonical, Confirmation.binding_hash == fingerprint).with_for_update())
            if (row.revision if row else 0) != confirmation_revision:
                raise HTTPException(409, "本会议参会人确认已变化，请重新读取")
            if row is None:
                row = Confirmation(owner=owner, task_id=canonical, binding_hash=fingerprint)
                db.add(row)
            row.note_key, row.evidence_revision = note_key, evidence_revision
            row.revision = confirmation_revision + 1
            row.participants_json = json.dumps(participants, ensure_ascii=False)
            row.confirmed_at = time.time()
            db.flush()
    except IntegrityError:
        raise HTTPException(409, "本会议参会人确认已变化，请重新读取") from None
    return _view(fresh, task_id, note_key, _stored(owner, canonical, binding), fresh_valid)


def resolve_saved_meeting(service, owner, note_key, *, title, content):
    """Fresh binding proofs for explicitly confirmed task attendees only.

    Search is bounded to one existing contact page per saved canonical name.
    Only the confirmed exact ID can be selected; a homonym never replaces it.
    Short-lived proofs are for the caller's current preparation and freezing.
    """
    result, task_id, binding, valid = _context(service, owner, note_key, title=title, content=content)
    canonical = result["canonical_task_id"]
    stored = _stored(owner, canonical, binding)
    result["confirmation_status"] = "unconfirmed"
    if not stored:
        # Legacy/current-task lookup only reports staleness, never migrates or
        # returns its names/proofs when the canonical origin cannot be verified.
        if canonical is None and _stored(owner, task_id, binding):
            result["confirmation_status"] = "stale"
        return result
    result["confirmation_revision"] = stored["revision"]
    if (not valid or stored["evidence_revision"] != result["evidence_revision"]):
        result["confirmation_status"] = "stale"
        result["unresolved"].append(_unresolved("attendance_confirmation_stale"))
        return result
    result["confirmation_status"] = "confirmed" if stored["participants"] else "cleared"
    from app.services.feishu_service import FeishuError

    for participant in stored["participants"]:
        target, name = participant["open_id"], participant["name"]
        try:
            if not 1 <= len(name) <= 50:
                raise ValueError("confirmed_contact_query_unsupported")
            _assert_binding(service, owner, binding)
            page = service.contacts(owner, name, page_size=50)
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise ValueError("confirmed_contact_invalid_response")
            matches = [item for item in page["items"] if isinstance(item, dict) and item.get("open_id") == target]
            if len(matches) != 1 or not isinstance(matches[0].get("selection_token"), str):
                raise ValueError("confirmed_contact_not_visible")
            selected = [{"open_id": target, "selection_token": matches[0]["selection_token"]}]
            proofs = _validated(service, owner, binding, selected)
            result["contacts"].extend(proofs)
        except ValueError as exc:
            allowed = {"confirmed_contact_query_unsupported", "confirmed_contact_not_visible", "confirmed_contact_invalid_response"}
            reason = str(exc) if str(exc) in allowed else "confirmed_contact_invalid_response"
            result["unresolved"].append({"open_id": target, "reason": reason})
        except (FeishuError, HTTPException) as exc:
            code = getattr(exc, "code", "")
            if code in {"connection_changed", "invalid_recipient"} or getattr(exc, "status_code", None) == 409:
                raise
            result["unresolved"].append({"open_id": target, "reason": "confirmed_contact_unavailable"})
    # Refreshes may change hotword caches, never the attendance scope.
    fresh, fresh_task, fresh_binding, fresh_valid = _context(service, owner, note_key, title=title, content=content)
    current = _stored(owner, canonical, binding)
    if (not fresh_valid or fresh_task != task_id or fresh_binding != binding
            or fresh["evidence_revision"] != result["evidence_revision"]
            or current is None or current["revision"] != stored["revision"]):
        result["contacts"] = []
        result["confirmation_status"] = "stale"
        result["unresolved"].append(_unresolved("attendance_confirmation_changed"))
        return result
    if result["contacts"]:
        confirmed_ids = {item["open_id"] for item in result["contacts"]}
        resolved_candidates = set()
        represented = set()
        for candidate in result["candidates"]:
            matches = confirmed_ids.intersection(candidate["matched_ids"])
            if len(matches) == 1:
                candidate["id"] = next(iter(matches))
                candidate["status"] = "user_confirmed"
                candidate["confidence"] = {"level": "user_confirmed", "reasons": ["explicit_meeting_confirmation"]}
                candidate["evidence"].append({"artifact": "user_confirmation", "revision": stored["revision"]})
                resolved_candidates.add(candidate["candidate_id"])
                represented.update(matches)
        for proof in result["contacts"]:
            if proof["open_id"] not in represented:
                result["candidates"].append({"candidate_id": _revision({"confirmed_id": proof["open_id"]}),
                    "name": proof["name"], "id": proof["open_id"], "matched_ids": [proof["open_id"]],
                    "status": "user_confirmed", "confidence": {"level": "user_confirmed", "reasons": ["explicit_meeting_confirmation"]},
                    "evidence": [{"artifact": "user_confirmation", "revision": stored["revision"]}]})
        result["unresolved"] = [item for item in result["unresolved"] if item["reason"] != "no_verified_attendance_identity"
                                and item.get("candidate_id") not in resolved_candidates]
    return result
