"""Conservative cross-surface association hypotheses.

No pixel coordinate is converted to world space here. Two tracks are linked
only through a shared remembered entity candidate, and confirmation remains an
addon/mouseover responsibility.
"""
from __future__ import annotations

import hashlib
from .models import canonical, number


class CrossViewAssociator:
    def associate(self, tracks: list[dict], recognitions: list[dict], at: float) -> list[dict]:
        by_track = {item.get("track_id"): item for item in tracks if item.get("track_id")}
        entity_tracks: dict[str, list[tuple[str, dict]]] = {}
        for recognition in recognitions:
            track_id = recognition.get("track_id")
            if track_id not in by_track:
                continue
            for match in recognition.get("entity_candidates", []):
                identity = match.get("identity_key")
                reliability = number(match.get("reliability")) or 0.
                if identity and reliability >= .55:
                    entity_tracks.setdefault(str(identity), []).append((track_id, match))
        result = []
        for entity, values in entity_tracks.items():
            for index, (left_id, left_match) in enumerate(values):
                for right_id, right_match in values[index+1:]:
                    left, right = by_track[left_id], by_track[right_id]
                    if left.get("source") == right.get("source"):
                        continue
                    confidence = min(number(left_match.get("reliability")) or 0,
                                     number(right_match.get("reliability")) or 0, .79)
                    seed = canonical({"left": left_id, "right": right_id, "entity": entity})
                    result.append({"association_id": hashlib.sha256(seed.encode()).hexdigest()[:24],
                        "left_track_id": left_id, "right_track_id": right_id,
                        "left_surface": left.get("source"), "right_surface": right.get("source"),
                        "entity_candidate": entity, "belief": "CANDIDATE",
                        "semantic_type": "UNKNOWN", "confidence": confidence,
                        "evidence": ["shared_visual_memory_entity_candidate"],
                        "coordinate_transform_used": False, "observed_at": at})
        return result


class CrossViewResolver(CrossViewAssociator):
    """Canonical read-only fusion API over the existing association evidence."""

    def _between(self, left_source: str, right_source: str, tracks: list[dict],
                 recognitions: list[dict], at: float) -> list[dict]:
        allowed = {left_source, right_source}
        selected = [track for track in tracks if track.get("source") in allowed]
        associations = self.associate(selected, recognitions, at)
        return [item for item in associations
                if {item.get("left_surface"), item.get("right_surface")} == allowed]

    def associate_map_to_minimap(self, tracks: list[dict], recognitions: list[dict],
                                 at: float) -> list[dict]:
        return self._between("WORLD_MAP_CV", "MINIMAP_CV", tracks, recognitions, at)

    def associate_minimap_to_world3d(self, tracks: list[dict], recognitions: list[dict],
                                     at: float) -> list[dict]:
        return self._between("MINIMAP_CV", "WORLD3D", tracks, recognitions, at)

    @staticmethod
    def associate_tooltip_to_track(mouseover, cursor_position, entities, *,
                                   screen_width: int, screen_height: int):
        from wowbot.vision.mouseover_association import associate_mouseover
        return associate_mouseover(mouseover, cursor_position, entities,
                                   screen_width=screen_width, screen_height=screen_height)

    @staticmethod
    def associate_target_to_entity(target: dict | None, entities: list[dict]) -> dict | None:
        guid = str((target or {}).get("guid") or "")
        if not guid:
            return None
        matches = [entity for entity in entities if str(entity.get("guid") or "") == guid]
        if not matches:
            return None
        return {"entity": matches[0], "identity": guid, "belief": "CONFIRMED",
                "confidence": 1.0, "evidence": ("addon_target_guid_exact",)}

    @staticmethod
    def resolve_conflicts(hypotheses: list[dict]) -> list[dict]:
        """Keep all evidence, but downgrade tracks supporting incompatible IDs."""
        identities: dict[str, set[str]] = {}
        for item in hypotheses:
            identity = str(item.get("entity_candidate") or "")
            for track_id in (item.get("left_track_id"), item.get("right_track_id")):
                if track_id and identity:
                    identities.setdefault(str(track_id), set()).add(identity)
        result = []
        for raw in hypotheses:
            item = dict(raw)
            conflicting = any(len(identities.get(str(track), ())) > 1
                              for track in (item.get("left_track_id"), item.get("right_track_id")))
            if conflicting:
                item["belief"] = "CONTRADICTED"
                item["confidence"] = min(float(item.get("confidence", 0)), .25)
                item["evidence"] = [*(item.get("evidence") or ()), "identity_conflict"]
            result.append(item)
        return result

    @staticmethod
    def get_best_entity_identity(hypotheses: list[dict]) -> dict | None:
        eligible = [item for item in hypotheses
                    if item.get("entity_candidate") and item.get("belief") != "CONTRADICTED"]
        if not eligible:
            return None
        best = max(eligible, key=lambda item: float(item.get("confidence", 0)))
        return {"identity_key": best["entity_candidate"],
                "confidence": float(best.get("confidence", 0)),
                "belief": best.get("belief", "CANDIDATE"),
                "evidence": tuple(best.get("evidence") or ())}
