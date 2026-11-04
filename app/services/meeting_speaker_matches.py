"""Bounded speaker/contact review projection; never identity inference or delivery."""
import math
from bisect import bisect_left, bisect_right
import re


def valid_speaker_id(value):
    return isinstance(value, str) and value not in {"speaker_unknown", "speaker_overlap"} and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def project_speakers(original, turns, candidates, snapshot):
    segments = original.get("segments", []) if isinstance(original, dict) else []
    rows = {}
    def row(speaker):
        if not valid_speaker_id(speaker) or (speaker not in rows and len(rows) >= 100):
            return None
        return rows.setdefault(speaker, {"speaker_id": speaker, "samples": [], "candidates": []})
    associations = {}
    for index, segment in enumerate(segments):
        speaker = segment.get("speaker_id")
        # Historical estimated sentence labels do not establish a real speaker.
        if segment.get("timestamp_estimated") or row(speaker) is None:
            continue
        linked = associations.setdefault(speaker, {})
        linked[index] = "segment_speaker"
    if isinstance(turns, dict):
        turns = turns.get("turns", [])
    turn_intervals = {}
    overlap_budget = 200000
    for turn in (turns if isinstance(turns, list) else [])[:10000]:
        if not isinstance(turn, dict):
            continue
        start, end = turn.get("start"), turn.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end):
            continue
        if row(turn.get("speaker_id")) is None:
            continue
        turn_intervals.setdefault(turn["speaker_id"], []).append((start, end))
        linked = associations.setdefault(turn["speaker_id"], {})
        # Small review samples only; overlap is explicitly NOT sentence identity.
        if len(linked) < 8 and overlap_budget > 0:
            for index, segment in enumerate(segments):
                overlap_budget -= 1
                if overlap_budget < 0:
                    break
                if segment["start"] < end and segment["end"] > start:
                    linked.setdefault(index, "time_overlap")
                    if len(linked) >= 8:
                        break
    names = {item.get("id"): item.get("name", "") for item in snapshot.get("objects", []) if isinstance(item, dict)}
    for speaker, value in rows.items():
        linked = associations.get(speaker, {})
        def interval_index(intervals):
            ordered = sorted(intervals)
            starts, ends = [], []
            for start, end in ordered:
                starts.append(start); ends.append(max(end, ends[-1] if ends else end))
            return starts, ends
        turn_starts, turn_ends = interval_index(turn_intervals.get(speaker, []))
        frame_starts, frame_ends = interval_index(
            [(segments[index]["start"], segments[index]["end"]) for index in linked if linked[index] == "segment_speaker"]
            + turn_intervals.get(speaker, []))
        # Candidate-bearing segments are checked against the complete bounded
        # turn set, independently of the short playback preview budget.
        for candidate in candidates:
            for index in candidate.get("_segment_indices", set()):
                position = bisect_left(turn_starts, segments[index]["end"]) - 1
                if position >= 0 and turn_ends[position] > segments[index]["start"]:
                    linked.setdefault(index, "time_overlap")
        preferred = []
        for candidate in candidates:
            indices = candidate.get("_segment_indices", {ref.get("segment_index") for ref in candidate.get("evidence", []) if ref.get("artifact") == "transcript.json"})
            preferred.extend(index for index in indices if index in linked)
        sample_indices = list(dict.fromkeys(sorted(preferred) + list(linked)))[:3]
        for index in sample_indices:
            segment = segments[index]
            value["samples"].append({"text": segment["text"][:240], "start": segment["start"], "end": segment["end"], "association": linked[index]})
        found = {}
        for candidate in candidates:
            references = candidate.get("evidence", [])
            indices = candidate.get("_segment_indices", {ref.get("segment_index") for ref in references if ref.get("artifact") == "transcript.json"})
            related = [index for index in indices if index in linked]
            offsets = candidate.get("_frame_offsets", set())
            visual = False
            for offset in offsets:
                position = bisect_right(frame_starts, offset) - 1
                if position >= 0 and frame_ends[position] > offset:
                    visual = True
                    break
            if not related and not visual:
                continue
            reasons = list(candidate.get("confidence", {}).get("reasons", []))
            if any(linked[index] == "time_overlap" for index in related):
                reasons.append("time_overlap_not_identity")
            if visual:
                reasons.extend(["visible_name_not_speaker_identity", "time_overlap_not_identity"])
            for target in candidate.get("matched_ids", []):
                entry = found.setdefault(target, {"open_id": target, "name": names.get(target, candidate["name"]), "reasons": []})
                entry["reasons"] = list(dict.fromkeys(entry["reasons"] + reasons))
        value["candidates"] = list(found.values())[:200]
    return list(rows.values())
