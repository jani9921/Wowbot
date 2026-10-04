"""V4 attention, semantic-evidence fusion and bounded hard-example capture."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from PIL import Image


class VisionSemanticFusion:
    """Enrich tracks with hypotheses while preserving UNKNOWN semantics."""

    ACTION_WORDS = {"accept", "continue", "complete quest", "goodbye", "decline"}

    def enrich(self, tracks: list[dict]) -> list[dict]:
        by_id = {track.get("track_id"): track for track in tracks}
        output = []
        for track in tracks:
            item = {**track}
            appearance = dict(item.get("appearance") or {})
            texts = list(appearance.get("ocr_evidence") or [])
            hypotheses = list(item.get("semantic_hypotheses") or [])
            labels = list(item.get("candidate_labels") or [])
            for text in texts:
                normalized = re.sub(r"\s+", " ", str(text.get("text") or "").casefold()).strip()
                if normalized:
                    labels.append("readable_text_like")
                if any(word in normalized for word in self.ACTION_WORDS):
                    labels.append("ui_action_text_like")
                    hypotheses.append({"type": "UI_ACTION_TEXT_LIKE", "belief": "CANDIDATE",
                                       "confidence": text.get("confidence", 0),
                                       "source": "TARGETED_OCR", "fact": False})
            relations = item.get("visual_relations") or []
            overhead = any(rel.get("type") == "ABOVE" and rel.get("belief") == "SUPPORTED"
                           for rel in relations)
            if overhead and texts and "subject" in str(item.get("detector_kind")):
                labels.append("quest_related_subject_like")
                hypotheses.append({"type": "QUEST_RELATED_SUBJECT_LIKE", "belief": "SUPPORTED",
                                   "confidence": min(.82, max(float(t.get("confidence", 0)) for t in texts)+.08),
                                   "sources": ["WORLD3D_TRACK", "OVERHEAD_RELATION", "TARGETED_OCR"],
                                   "fact": False})
            # A related symbol/subject may be linked in either direction. This
            # is a scene-graph edge, not an NPC or quest-role assertion.
            for relation in relations:
                other_id = relation.get("subject_track_id") or relation.get("symbol_track_id")
                if other_id in by_id:
                    relation.setdefault("associated_track_exists", True)
            item["appearance"] = appearance
            item["candidate_labels"] = list(dict.fromkeys(labels))
            item["semantic_hypotheses"] = hypotheses
            item["semantic_type"] = "UNKNOWN"
            item["confirmed"] = False
            output.append(item)
        return output


class HardExampleCollector:
    """Bounded local dataset for ambiguous, persistent UNKNOWN tracks."""

    def __init__(self, directory: Path | None, *, limit: int = 200, cooldown: float = 15.):
        self.directory = Path(directory) if directory else None
        self.limit = max(0, int(limit))
        self.cooldown = max(1., float(cooldown))
        self.last_seen: dict[str, float] = {}
        self.saved = (len(list(self.directory.glob("*.json")))
                      if self.directory and self.directory.is_dir() else 0)
        self.status = ("disabled" if self.directory is None else
                       "limit_reached" if self.saved >= self.limit else "ready")

    def consider(self, raw: bytes, width: int, height: int,
                 tracks: list[dict], observed_at: float) -> int:
        if self.directory is None or self.saved >= self.limit:
            return 0
        chosen = []
        for track in tracks:
            if (track.get("semantic_type") != "UNKNOWN"
                    or track.get("detector_kind") not in {
                        "unknown_subject_candidate", "unknown_subject_probe",
                        "unknown_object_candidate", "obstacle_candidate"}):
                continue
            state = str(track.get("track_state") or track.get("lifecycle") or "")
            reasons = list(track.get("hard_example_reasons") or ())
            confidence = float(track.get("confidence", 0) or 0)
            hypotheses = track.get("detection_hypotheses") or {}
            if confidence < .55:
                reasons.append("low_confidence")
            if isinstance(hypotheses, dict) and len(hypotheses) > 1:
                reasons.append("detector_disagreement")
            if track.get("identity_correction"):
                reasons.append("wrong_identity_later_confirmed")
            if track.get("quest_role_penalty"):
                reasons.append("quest_no_credit_after_target")
            if state in {"LOST", "LOST_TEMPORARY", "TERMINATED"}:
                reasons.append("track_loss")
            if track.get("false_obstacle_feedback"):
                reasons.append("false_obstacle")
            if track.get("failed_entrance_feedback"):
                reasons.append("failed_entrance_candidate")
            if (state in {"STABLE", "ACTIVE", "REACQUIRED"}
                    and not (track.get("appearance") or {}).get("ocr_evidence")):
                reasons.append("persistent_unresolved_unknown")
            if reasons:
                chosen.append(({**track, "_hard_example_reasons": sorted(set(reasons))}))
        if not chosen:
            return 0
        image = None
        written = 0
        self.directory.mkdir(parents=True, exist_ok=True)
        for track in sorted(chosen, key=lambda item: -float(item.get("confidence", 0)))[:2]:
            bbox = track.get("bbox") or {}
            if not all(isinstance(bbox.get(k), (int, float)) for k in ("left", "top", "right", "bottom")):
                continue
            key = str(track.get("track_id"))
            if observed_at-self.last_seen.get(key, -1e9) < self.cooldown:
                continue
            left, top = max(0, int(bbox["left"])), max(0, int(bbox["top"]))
            right, bottom = min(width, int(bbox["right"])), min(height, int(bbox["bottom"]))
            if right-left < 8 or bottom-top < 8:
                continue
            if image is None:
                image = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")
            token = hashlib.sha256(f"{key}:{observed_at:.3f}:{left}:{top}:{right}:{bottom}".encode()).hexdigest()[:20]
            image.crop((left, top, right, bottom)).save(self.directory / f"{token}.png")
            identity = track.get("identity_belief") or {}
            metadata = {"sample_id": token, "track_id": key, "observed_at": observed_at,
                        "bbox": {"left": left, "top": top, "right": right, "bottom": bottom},
                        "semantic_type": "UNKNOWN", "label_status": "UNLABELED_HARD_EXAMPLE",
                        "candidate_labels": track.get("candidate_labels", []),
                        "confidence": track.get("confidence"),
                        "trigger_reasons": track.get("_hard_example_reasons", []),
                        "detector_outputs": track.get("detection_hypotheses", {}),
                        "final_label": (identity.get("identity")
                                        if identity.get("state") == "CONFIRMED" else None),
                        "provenance": {"source": "WORLD3D", "collector": "VISION_V4"}}
            (self.directory / f"{token}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            self.last_seen[key] = observed_at
            self.saved += 1
            written += 1
            if self.saved >= self.limit:
                break
        self.status = "limit_reached" if self.saved >= self.limit else "ready"
        return written

    def diagnostics(self) -> dict:
        return {"status": self.status, "saved": self.saved, "limit": self.limit,
                "directory": str(self.directory) if self.directory else None}
