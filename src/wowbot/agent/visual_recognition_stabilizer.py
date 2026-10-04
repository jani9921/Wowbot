"""Passive visual re-identification helpers extracted from runtime.py (V4-083/V4-095).

Mechanical extraction only -- no behavior change. These three symbols were
previously defined directly in ``runtime.py``; they have no dependency on
``AgentRuntime``'s instance state, so they were moved here verbatim and
``runtime.py`` now imports them, reducing that file's size without altering
what it does. Existing callers that import them from ``wowbot.agent.runtime``
(e.g. ``tests/test_agent_runtime.py``) are unaffected -- Python module
attributes work the same whether defined locally or re-exported via import.
"""
from __future__ import annotations

import math


def _manual_mouseover_learning_probe(payload: dict | None, candidates: list[dict]) -> dict | None:
    """Return the exact current World3D crop for passive mouseover learning.

    This is intentionally narrower than active INSPECT: it has no input or
    planner authority.  It accepts only a simultaneous addon GUID and cursor
    sample that lies on an already tracked, signed UNKNOWN subject.  The addon
    remains identity ground truth; the returned candidate is merely the visual
    crop to teach against that identity.
    """
    if not isinstance(payload, dict):
        return None
    mouse = payload.get("mouseover") or {}
    cursor = payload.get("cursor_position") or {}
    guid = mouse.get("guid") if isinstance(mouse, dict) else None
    try:
        x, y = float(cursor.get("nx")), float(cursor.get("ny"))
        cursor_at, mouse_at = float(payload.get("cursor_sample_time")), float(payload.get("mouseover_sample_time"))
    except (TypeError, ValueError):
        return None
    if (not guid or not (math.isfinite(x) and math.isfinite(y))
            or not (.02 < x < .98 and .02 < y < .98)
            or not (math.isfinite(cursor_at) and math.isfinite(mouse_at))
            or abs(cursor_at-mouse_at) > .05):
        return None
    subjects = [item for item in candidates
                if item.get("source") == "WORLD3D"
                and "subject" in str(item.get("detector_kind") or item.get("kind") or "")
                and isinstance(item.get("visual_signature"), dict)]
    scored = []
    for item in subjects:
        try:
            distance = math.hypot(float(item.get("x"))-x, float(item.get("y"))-y)
        except (TypeError, ValueError):
            continue
        if distance <= .015:
            scored.append((distance, item))
    if not scored:
        return None
    distance, candidate = min(scored, key=lambda row: row[0])
    return {**candidate, "manual_mouseover_ground_truth": True,
            "mouseover_association_distance": round(distance, 6)}


def _publishable_visual_matches(matches: list[dict]) -> list[dict]:
    """Keep EntityMemory's broad search internal; publish only precise cues.

    `EntityMemory` may retain a looser approximate lookup for offline recall
    and diagnostics.  A live World3D observation is much more ambiguous,
    particularly with adjacent creatures, so low-similarity approximate
    matches must not enter the WorldModel as active visual evidence.
    """
    published = []
    for match in matches:
        # An ``unknown:*`` key is a persistence fallback, not a complete
        # entity identity.  It may remain useful in EntityMemory diagnostics,
        # but visual resemblance must not promote it to live WorldModel
        # evidence without a current addon ground-truth association.
        if str(match.get("identity_key") or "").startswith("unknown:"):
            continue
        method = str(match.get("match_method") or "")
        if method in {"APPROXIMATE_VISUAL_REIDENTIFICATION",
                      "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"}:
            try:
                if float(match.get("similarity", 0.)) < .90:
                    continue
            except (TypeError, ValueError):
                continue
        published.append(match)
    return published


class _VisualRecognitionStabilizer:
    """Turn per-frame visual re-identification into track-local evidence.

    Visual similarity is deliberately not an addon identity fact.  In
    particular, two adjacent creatures can create one-frame alternative
    matches as detector crops change.  This passive filter needs repeated
    support on the same temporal track before the candidate is published to
    the WorldModel; it has no planner or input authority.
    """
    _DECAY_SECONDS = 1.2
    _PUBLISH_SCORE = 2.35
    _WIN_MARGIN = .25
    _MAX_AGE_SECONDS = 3.0

    def __init__(self):
        self._evidence: dict[tuple[str, str], dict] = {}

    def update(self, track_id: str | None, matches: list[dict], now: float) -> list[dict]:
        track = str(track_id or "")
        if not track:
            return []
        current = {str(match.get("identity_key") or ""): match for match in matches
                   if str(match.get("identity_key") or "")}
        for key in list(self._evidence):
            if key[0] == track and now - float(self._evidence[key]["at"]) > self._MAX_AGE_SECONDS:
                del self._evidence[key]
        updated: dict[str, tuple[dict, float, int]] = {}
        for identity, match in current.items():
            key = (track, identity)
            prior = self._evidence.get(key)
            previous_score = 0.
            frame_count = 0
            if prior is not None:
                elapsed = max(0., now - float(prior["at"]))
                previous_score = float(prior["score"]) * math.exp(-elapsed / self._DECAY_SECONDS)
                frame_count = int(prior["frames"])
            score = previous_score + float(match.get("similarity", 0.))
            frame_count += 1
            self._evidence[key] = {"at": now, "score": score, "frames": frame_count,
                                   "match": dict(match)}
            updated[identity] = (match, score, frame_count)
        eligible = [(identity, match, score, frames) for identity, (match, score, frames) in updated.items()
                    if score >= self._PUBLISH_SCORE]
        if not eligible:
            return []
        eligible.sort(key=lambda item: item[2], reverse=True)
        if len(eligible) > 1 and eligible[0][2] - eligible[1][2] < self._WIN_MARGIN:
            return []
        _, match, score, frames = eligible[0]
        return [{**match, "temporal_support_frames": frames,
                 "temporal_evidence_score": round(score, 4)}]
