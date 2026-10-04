"""Per-quest visual prototypes: inspect what looks like the confirmed targets.

User 2026-10-04: "it should see what shape it had to kill for the quest, drop
the tracks that do not fit, and inspect only similar ones".  Every addon
hover is a free label for the box under the cursor:

* POSITIVE for a quest: the hovered unit is alive and the tooltip / name ties
  it to an open quest (``quest_id``);
* NEGATIVE: a corpse, or a unit the hover showed is not tied to any open
  quest.

Boxes get ``prototype_positive`` / ``prototype_negative`` (best cosine
similarity of their appearance embedding) and ``prototype_lift`` in [-1, 1]:
how much closer they are to an open quest's confirmed targets than to the
rejected looks.  ActivePerception uses the lift only to order mouseover
probes; the hover stays the identity authority, so a wrong prototype costs
a probe, never a wrong action.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

from .models import number

MAX_PER_QUEST = 24
MAX_NEGATIVE = 60
MARGIN = .08          # similarity difference that maps to a full +/-1 lift


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.
    return float(sum(x*y for x, y in zip(a, b)))


def candidate_embedding(item: dict) -> list[float] | None:
    signature = item.get("visual_signature") if isinstance(item.get("visual_signature"), dict) else {}
    embedding = signature.get("embedding")
    return embedding if isinstance(embedding, list) and embedding else None


class VisualPrototypeMemory:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.positive: dict[str, list[dict]] = {}
        self.negative: list[dict] = []
        self.dirty = False
        self.saved_at = 0.
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.positive = {str(key): list(value) for key, value in (data.get("positive") or {}).items()}
                self.negative = list(data.get("negative") or [])
            except (OSError, ValueError, AttributeError):
                self.positive, self.negative = {}, []

    # ----------------------------------------------------------------- learn
    def add(self, embedding, *, positive: bool, quest_id=None, guid=None, name=None,
            reason: str = "", at: float | None = None) -> bool:
        if not embedding:
            return False
        entry = {"embedding": list(embedding), "guid": guid, "name": name, "reason": reason,
                 "at": at if at is not None else time.time()}
        if positive:
            if quest_id is None:
                return False
            bucket = self.positive.setdefault(str(quest_id), [])
        else:
            bucket = self.negative
        # One sample per unit and label: refresh it instead of piling up.
        bucket[:] = [item for item in bucket if not guid or item.get("guid") != guid]
        bucket.append(entry)
        del bucket[:-(MAX_PER_QUEST if positive else MAX_NEGATIVE)]
        self.dirty = True
        return True

    def observe_hover(self, state: dict, *, guid: str, unit: dict, track_id,
                      quest_id, open_quest_ids, at: float) -> str | None:
        """Label the hovered box; return POSITIVE/NEGATIVE or None."""
        item = next((candidate for candidate in state.get("visual_candidates") or ()
                     if isinstance(candidate, dict) and track_id is not None
                     and candidate.get("track_id") == track_id), None)
        embedding = candidate_embedding(item) if item else None
        if embedding is None or (item.get("appearance") or {}).get("self_player_avatar"):
            return None
        dead = unit.get("is_dead", unit.get("dead")) is True
        if not dead and quest_id is not None and str(quest_id) in open_quest_ids:
            self.add(embedding, positive=True, quest_id=quest_id, guid=guid, name=unit.get("name"),
                     reason="HOVER_QUEST_RELEVANT", at=at)
            return "POSITIVE"
        if dead or (open_quest_ids and quest_id is None and unit.get("quest_related") is not True):
            self.add(embedding, positive=False, guid=guid, name=unit.get("name"),
                     reason="HOVER_CORPSE" if dead else "HOVER_NOT_QUEST_RELEVANT", at=at)
            return "NEGATIVE"
        return None

    # ----------------------------------------------------------------- score
    def annotate(self, candidates, open_quest_ids) -> int:
        """Write prototype similarity/lift onto WORLD3D subject candidates."""
        if not open_quest_ids:
            return 0          # nothing to hunt: hovering friendly NPCs (turn-in) stays neutral
        positives = [entry["embedding"] for quest_id in open_quest_ids
                     for entry in self.positive.get(str(quest_id), ())]
        negatives = [entry["embedding"] for entry in self.negative]
        rows = []
        for item in candidates or ():
            if (not isinstance(item, dict) or item.get("source") != "WORLD3D"
                    or "subject" not in str(item.get("detector_kind") or item.get("kind") or "")):
                continue
            embedding = candidate_embedding(item)
            if embedding is None:
                continue
            positive = max((_cosine(embedding, other) for other in positives), default=None)
            negative = max((_cosine(embedding, other) for other in negatives), default=None)
            rows.append((item, positive, negative))
        if not rows or not (positives or negatives):
            return 0
        # A box must beat both the rejected looks and the scene's typical box
        # (the median positive similarity; histograms are all somewhat alike).
        observed = sorted(value for _, value, _ in rows if value is not None)
        baseline = observed[len(observed)//2] if len(observed) >= 3 else None
        for item, positive, negative in rows:
            references = [value for value in (negative, baseline) if value is not None]
            reference = max(references) if references else None
            lift = 0.
            if positive is not None and reference is not None:
                lift = max(-1., min(1., (positive-reference)/MARGIN))
            elif negative is not None and positive is None:
                lift = -max(0., min(1., (negative-.85)/.1))   # only rejected looks known
            appearance = dict(item.get("appearance") or {})
            appearance.update({"prototype_positive": None if positive is None else round(positive, 4),
                               "prototype_negative": None if negative is None else round(negative, 4),
                               "prototype_lift": round(lift, 4)})
            item["appearance"] = appearance
        return len(rows)

    # ----------------------------------------------------------------- persist
    def save(self, now: float | None = None, *, force: bool = False) -> None:
        now = time.monotonic() if now is None else now
        if not self.path or not self.dirty or (not force and now-self.saved_at < 10.):
            return
        try:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"positive": self.positive, "negative": self.negative}),
                                 encoding="utf-8")
            os.replace(temporary, self.path)
            self.dirty, self.saved_at = False, now
        except OSError:
            pass

    def snapshot(self) -> dict:
        return {"positive": {key: len(value) for key, value in self.positive.items()},
                "negative": len(self.negative)}


def memory_for(model) -> VisualPrototypeMemory:
    memory = model.__dict__.get("visual_prototypes")
    if memory is None:
        memory = model.__dict__["visual_prototypes"] = VisualPrototypeMemory()
    return memory


def open_quest_ids(state: dict) -> set[str]:
    return {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
            if isinstance(quest, dict) and quest.get("quest_id") is not None
            and quest.get("is_complete") is not True}
