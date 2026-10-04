"""Canonical query-state projection for ``WorldModel``.

The projector is stateless and writes only the supplied model.  It combines
source-scoped projections, prunes short-lived screen anchors and associates a
confirmed mouseover identity with the nearest current UNKNOWN visual track.
It does not ingest observations, decide actions, or own a second world state.
"""
from __future__ import annotations

from .self_avatar import is_self_avatar_box

from copy import deepcopy as _slow_deepcopy
import math
from typing import TYPE_CHECKING

from .models import number

if TYPE_CHECKING:
    from .world import WorldModel


def _copy(value):
    value_type = type(value)
    if value_type is dict:
        return {key: _copy(item) for key, item in value.items()}
    if value_type is list:
        return [_copy(item) for item in value]
    if value_type is tuple:
        return tuple(_copy(item) for item in value)
    if value_type in {str, int, float, bool} or value is None:
        return value
    return _slow_deepcopy(value)


class WorldStateProjector:
    _METADATA_KEYS = frozenset({
        "session_id", "timestamp", "frame_id", "surface", "confidence", "provenance",
    })
    _LIST_FIELDS = frozenset({
        "visual_candidates", "remembered_locations", "map_marker_observations",
        "semantic_memory_facts",
    })

    def rebuild(self, model: "WorldModel") -> None:
        model.state = _copy(model.addon_state)
        combined = {key: [] for key in self._LIST_FIELDS}
        for projection in model.projections.values():
            for key, value in projection.items():
                if key in self._METADATA_KEYS:
                    continue
                if key in self._LIST_FIELDS and isinstance(value, list):
                    combined[key].extend(_copy(value))
                else:
                    model.state[key] = _copy(value)
        for key, values in combined.items():
            if values or any(key in projection for projection in model.projections.values()):
                model.state[key] = values
        self._project_vehicle_bar(model.state)
        self._project_fast_actionbar(model.state)
        self._project_camera(model.state)
        self._project_self_avatar_identity(model)
        self._project_self_player_tracks(model.state)
        self._project_visual_prototypes(model)
        self._prune_transient_memory(model)
        self._project_confirmed_semantics(model)
        self._project_selected_target_anchor(model)
        self._project_target_minimap_position(model)
        self._associate_visual_tracks(model)
        model.state["confirmed_corpse_anchors"] = [
            _copy(anchor) for anchor in model.corpse_anchors.values()]
        model.state["owned_corpse_guids"] = list(model.owned_corpse_guids)
        model.state["confirmed_mouseover_anchors"] = _copy(model.mouseover_screen_anchors)
        model.state["mouseover_object_memory"] = _copy(
            model.__dict__.get("mouseover_object_memory") or {})
        model.state["confirmed_entity_semantics"] = _copy(model.mouseover_entity_semantics)
        model.state["quest_turn_in_names"] = _copy(model.__dict__.get("quest_turn_in") or {})

    def refresh_fast(self, model: "WorldModel", fast_delta: dict) -> None:
        """Apply authoritative FAST fields without cloning every CV projection.

        Position/orientation/movement arrive tens of times per second.  The
        former full rebuild copied the complete World3D batch (including track
        histories) for every one of those samples even though no visual
        projection had changed.  Supplemental observations still mark the
        model dirty and receive a normal atomic rebuild; this path only avoids
        unrelated projection work for an addon-only FAST update.
        """
        if not model.state:
            self.rebuild(model)
            return
        for key, value in fast_delta.items():
            model.state[key] = _copy(value)
        self._project_vehicle_bar(model.state)
        self._project_fast_actionbar(model.state)
        self._project_camera(model.state)
        self._project_self_avatar_identity(model)
        self._project_self_player_tracks(model.state)
        self._prune_transient_memory(model)
        self._project_confirmed_semantics(model)
        self._project_selected_target_anchor(model)
        self._project_target_minimap_position(model)
        self._associate_visual_tracks(model)
        model.state["confirmed_corpse_anchors"] = [
            _copy(anchor) for anchor in model.corpse_anchors.values()]
        model.state["owned_corpse_guids"] = list(model.owned_corpse_guids)
        model.state["confirmed_mouseover_anchors"] = _copy(model.mouseover_screen_anchors)
        model.state["mouseover_object_memory"] = _copy(
            model.__dict__.get("mouseover_object_memory") or {})
        model.state["confirmed_entity_semantics"] = _copy(model.mouseover_entity_semantics)
        model.state["quest_turn_in_names"] = _copy(model.__dict__.get("quest_turn_in") or {})

    @staticmethod
    def _project_fast_actionbar(state: dict) -> None:
        """Keep the canonical actionbar identity, refresh volatile facts."""
        fresh_by_id = {}
        for entry in state.get("actionbar_fast") or ():
            if isinstance(entry, (list, tuple)) and len(entry) >= 4:
                fresh_by_id[entry[0]] = {
                    "is_usable": entry[1], "in_range": entry[2],
                    "cooldown_remaining": entry[3],
                }
            elif isinstance(entry, dict):
                spell_id = entry.get("id", entry.get("spell_id"))
                if spell_id is not None:
                    fresh_by_id[spell_id] = {
                        key: entry.get(key) for key in
                        ("is_usable", "in_range", "cooldown_remaining")
                        if key in entry
                    }
        if not fresh_by_id:
            return
        state["actionbar"] = [
            {**action, **fresh_by_id.get(action.get("id", action.get("spell_id")), {})}
            if isinstance(action, dict) else action
            for action in state.get("actionbar") or ()
        ]

    @staticmethod
    def _project_camera(state: dict) -> None:
        camera = state.get("camera_state") or {}
        motion = camera.get("camera_motion_px") or {}
        state.update({
            "camera_yaw_estimate": camera.get("yaw_estimate", motion.get("dx")),
            "camera_pitch_estimate": camera.get("pitch_estimate", motion.get("dy")),
            "camera_zoom_estimate": camera.get("zoom_estimate"),
            "camera_relative_to_player_heading": camera.get("relative_to_player_heading"),
            "last_camera_action": camera.get("last_action"),
            "camera_motion_confidence": camera.get(
                "motion_confidence", motion.get("confidence", 0.)),
            "camera_state_status": "ESTIMATED",
        })

    def _prune_transient_memory(self, model: "WorldModel") -> None:
        now = model.last_received
        model.looted_corpse_guids = {
            guid: looted_at for guid, looted_at in model.looted_corpse_guids.items()
            if 0 <= now - looted_at <= 300.}
        model.owned_corpse_guids = {
            guid: killed_at for guid, killed_at in model.owned_corpse_guids.items()
            if 0 <= now - killed_at <= 180.}
        model.corpse_anchors = {
            guid: anchor for guid, anchor in model.corpse_anchors.items()
            if 0 <= now - (number(anchor.get("observed_at")) or -math.inf) <= 20.
            and not model.corpse_was_recently_looted(guid, now)}
        model.mouseover_screen_anchors = {
            guid: anchor for guid, anchor in model.mouseover_screen_anchors.items()
            if 0 <= now - (number(anchor.get("observed_at")) or -math.inf) <= 30.
            and self.screen_anchor_scene_valid(anchor, model.state)}
        active_quests = {
            str(quest.get("quest_id")): quest
            for quest in model.state.get("active_quests", [])
            if quest.get("quest_id") is not None
        }
        model.mouseover_entity_semantics = {
            guid: semantic
            for guid, semantic in model.mouseover_entity_semantics.items()
            if 0 <= now - (number(semantic.get("observed_at")) or -math.inf) <= 120.
            and str(semantic.get("quest_id")) in active_quests
            and active_quests[str(semantic.get("quest_id"))].get("is_complete") is not True
        }

    @staticmethod
    def _project_confirmed_semantics(model: "WorldModel") -> None:
        # Identity/quest meaning may follow the exact GUID; old screen pixels do not.
        target = model.state.get("target")
        if not isinstance(target, dict):
            return
        semantic = model.mouseover_entity_semantics.get(str(target.get("guid") or ""))
        if not semantic and target.get("npc_id") is not None:
            from .tooltip_quest import objective_still_open
            kind = (model.__dict__.get("quest_relevant_npcs") or {}).get(str(target["npc_id"]))
            if (kind and target.get("attackable", target.get("is_attackable")) is True
                    and objective_still_open(model.state, kind.get("quest_id"),
                                             kind.get("objectives") or ())):
                semantic = kind
        if semantic:
            target["quest_relevant"] = True
            target["quest_related"] = True
            target["quest_id"] = semantic.get("quest_id")

    @staticmethod
    def _project_vehicle_bar(state: dict) -> None:
        """While a vehicle/override bar is active, its actions are the bar.

        Live 2026-10-04 (Ride of the Scientifically Enhanced Boar): the
        ridden Giant Boar's abilities replace the main bar; ACTIONBUTTON1..12
        fire them.  Addon 0.9.49 exports them as ``vehicle_bar``; combat and
        skill availability keep reading ``actionbar``.
        """
        bar = state.get("vehicle_bar")
        actions = [action for action in (bar or {}).get("actions") or ()
                   if isinstance(action, dict) and action.get("action")]
        if not actions or (state.get("in_vehicle") is False and bar.get("kind") in {"VEHICLE", "OVERRIDE"}):
            state["vehicle_controls"] = False
            return
        if state.get("actionbar") is not actions:
            state["player_actionbar"] = state.get("player_actionbar") or state.get("actionbar")
        state["actionbar"] = _copy(actions)
        state["vehicle_controls"] = True

    REACTION_COLOURS = {"hostile": {"RED"}, "neutral": {"YELLOW"}, "friendly": {"GREEN"}}

    @staticmethod
    def _project_target_minimap_position(model: "WorldModel") -> None:
        """Estimate the selected unit's WORLD_YARDS position from its minimap marker.

        User 2026-10-04: the current target is drawn on the minimap as a
        reaction-coloured dot inside a gold crosshair, shown only for the
        target.  Retail exposes no NPC position, so this is the only bearing
        and distance for an off-screen target (e.g. a ranged caster).  It is
        an estimate (``source=MINIMAP_TARGET_MARKER``, ~view radius / disc
        px yards precise), never identity: the GUID still comes from the addon.
        """
        target = model.state.get("target")
        if (not isinstance(target, dict) or not target.get("guid")
                or isinstance(target.get("world_position"), dict)):
            return
        candidate = next((item for item in model.state.get("visual_candidates") or ()
                          if isinstance(item, dict) and item.get("kind") == "minimap_target_marker"
                          and item.get("markers")), None)
        position = model.state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        geometry = model.state.get("minimap_geometry") or {}
        view = (number((candidate or {}).get("view_radius_yards"))
                or number(geometry.get("view_radius_yards")))
        if candidate is None or px is None or py is None or not view:
            return
        reaction = str(target.get("reaction") or "").casefold()
        colours = WorldStateProjector.REACTION_COLOURS.get(reaction)
        if colours is None:
            attackable = target.get("attackable", target.get("is_attackable"))
            colours = {"GREEN"} if attackable is False else {"RED", "YELLOW"} if attackable else None
        markers = [marker for marker in candidate["markers"]
                   if colours is None or marker.get("colour") in colours]
        if len(markers) != 1:
            return            # none, or ambiguous: no position rather than a wrong one
        from wowbot.vision.minimap_quest_area import offsets_to_world
        rotate = bool(candidate.get("rotate_minimap", geometry.get("rotate_minimap")))
        (wx, wy), = offsets_to_world([markers[0]["offset"]], player_x=px, player_y=py,
                                     view_radius_yards=view, rotate=rotate,
                                     facing=number(model.state.get("orientation")))
        target["world_position"] = {
            "x": round(wx, 1), "y": round(wy, 1), "coordinate_space": "WORLD_YARDS",
            "instance_id": position.get("instance_id"), "z_known": False,
            "source": "MINIMAP_TARGET_MARKER", "marker_colour": markers[0].get("colour"),
            "observed_at": candidate.get("observed_at"),
        }

    @staticmethod
    def _project_selected_target_anchor(model: "WorldModel") -> None:
        """Link an exact selected GUID to its nameplate and current CV track.

        This is association, not recognition: the addon owns target identity;
        World3D contributes only a continuously tracked screen location.  It
        enables visual servoing when Retail does not expose a world XYZ for a
        dynamic creature.
        """
        target = model.state.get("target")
        if not isinstance(target, dict) or not target.get("guid"):
            return
        anchor = _copy(target.get("screen_position") or {})
        exact_plate = next((plate for plate in model.state.get("nameplates") or ()
                            if isinstance(plate, dict)
                            and str(plate.get("guid") or "") == str(target["guid"])
                            and number(plate.get("nx")) is not None
                            and number(plate.get("ny")) is not None), None)
        if not anchor and exact_plate:
            anchor = {
                "x": number(exact_plate.get("nx")),
                "y": number(exact_plate.get("ny")),
                "source": "NAMEPLATE_API",
                "coordinate_space": "CLIENT_BOTTOM_LEFT",
                "sample_time": number(exact_plate.get("sample_time")),
                "identity_source": "EXACT_GUID_NAMEPLATE",
            }
        if not anchor:
            anchor = WorldStateProjector._bound_track_anchor(model, str(target["guid"]))
        if number(anchor.get("x")) is None or number(anchor.get("y")) is None:
            return

        # The plate is above its subject.  Prefer a current generic subject
        # proposal directly below it; appearance never supplies the GUID.
        # Live 2026-10-04 (Giant Boar): a BOUND_WORLD3D_TRACK anchor *is* the
        # subject's own box centre.  Searching "below" it picked the ridden
        # boar + rider box under a distant Monstrous Cadaver, remembered it
        # as the target box, and steering/Trample followed the own avatar.
        bound_track = (str(anchor.get("track_id"))
                       if anchor.get("source") == "BOUND_WORLD3D_TRACK"
                       and anchor.get("track_id") is not None else None)
        candidates = []
        for item in model.state.get("visual_candidates") or ():
            if bound_track is not None:
                if (isinstance(item, dict) and str(item.get("track_id")) == bound_track
                        and not is_self_avatar_box(item)):
                    candidates.append((0., item))
                continue
            if (not isinstance(item, dict) or item.get("source") != "WORLD3D"
                    or is_self_avatar_box(item)):
                continue
            kind = str(item.get("detector_kind") or item.get("kind") or "").casefold()
            if not any(token in kind for token in ("subject", "entity", "character", "mob", "npc")):
                continue
            x, y = number(item.get("x")), number(item.get("y"))
            if x is None or y is None:
                center = item.get("screen_center") or {}
                x, y = number(center.get("x")), number(center.get("y"))
                if y is not None and center.get("coordinate_space") == "WORLD_VIEWPORT_NORMALIZED":
                    y = 1.-y
            if x is None or y is None:
                continue
            dx, below = abs(x-float(anchor["x"])), float(anchor["y"])-y
            if dx <= .20 and -.04 <= below <= .42:
                candidates.append((dx + max(0., below-.18)*.5, item))
        if bound_track is not None and not candidates:
            return            # its box is gone or is the own avatar: no stale bbox
        if candidates:
            _, subject = min(candidates, key=lambda pair: pair[0])
            anchor.update({
                "track_id": subject.get("track_id"),
                "bbox": _copy(subject.get("bbox")),
                "bbox_height_fraction": subject.get("bbox_height_fraction"),
                "track_confidence": subject.get("confidence"),
                "track_association": "CONFIRMED_GUID_NAMEPLATE",
                "visual_signature": _copy(subject.get("visual_signature")),
            })
            target["visual_track_id"] = subject.get("track_id")
            boxes = getattr(model, "last_target_boxes", None)
            if isinstance(boxes, dict) and isinstance(anchor.get("bbox"), dict):
                boxes[str(target["guid"])] = {
                    "x": anchor.get("x"), "y": anchor.get("y"),
                    "track_id": anchor.get("track_id"), "bbox": _copy(anchor["bbox"]),
                    "bbox_height_fraction": anchor.get("bbox_height_fraction"),
                    "bbox_width_fraction": subject.get("bbox_width_fraction"),
                    "coordinate_space": "CLIENT_BOTTOM_LEFT",
                    "observed_at": number(model.state.get("monotonic_time")),
                }
        target["screen_position"] = anchor

    @staticmethod
    def _bound_track_anchor(model: "WorldModel", guid: str) -> dict:
        """Current box of the track the selected GUID was bound to.

        Retail 12 exposes neither the target's screen position nor nameplate
        positions (user 2026-10-02), so combat facing never had a bearing
        live.  Targets are selected by clicking a hovered box whose World3D
        track the addon mouseover GUID was associated with; follow that
        track (or the one remembered from an earlier binding).
        """
        remembered = (getattr(model, "last_target_boxes", None) or {}).get(guid) or {}
        hovered = (getattr(model, "mouseover_screen_anchors", None) or {}).get(guid) or {}
        track_ids = [str(value) for value in (remembered.get("track_id"), hovered.get("track_id"))
                     if value is not None]
        if not track_ids:
            return {}
        by_track = {str(item.get("track_id")): item
                    for item in model.state.get("visual_candidates") or ()
                    if isinstance(item, dict) and item.get("source") == "WORLD3D"
                    and item.get("track_id") is not None and not is_self_avatar_box(item)}
        for track_id in track_ids:
            item = by_track.get(track_id)
            x, y = (number(item.get("x")), number(item.get("y"))) if item else (None, None)
            if x is None or y is None:
                continue
            return {
                "x": x, "y": y, "source": "BOUND_WORLD3D_TRACK",
                "coordinate_space": "CLIENT_BOTTOM_LEFT",
                "sample_time": number(item.get("observed_at")) or number(model.state.get("monotonic_time")),
                "identity_source": "HOVER_SELECTED_TRACK",
                "track_id": item.get("track_id"),
            }
        return {}

    @staticmethod
    def _project_visual_prototypes(model: "WorldModel") -> None:
        """Similarity of each box to this quest's confirmed target looks."""
        from .visual_prototypes import memory_for, open_quest_ids
        memory = memory_for(model)
        memory.annotate(model.state.get("visual_candidates") or (), open_quest_ids(model.state))
        model.state["visual_prototypes"] = memory.snapshot()

    @staticmethod
    def _project_self_avatar_identity(model: "WorldModel") -> None:
        """Zoom/vehicle independent avatar identity (see ``self_avatar``)."""
        from .self_avatar import SelfAvatarIdentifier
        identifier = model.__dict__.get("self_avatar_identifier")
        if identifier is None:
            identifier = model.__dict__["self_avatar_identifier"] = SelfAvatarIdentifier()
        state = model.state
        for item in state.get("visual_candidates") or ():
            # refresh_fast keeps the previous candidate dicts: drop our own
            # earlier marks so a vetoed box does not stay suppressed.
            appearance = item.get("appearance") if isinstance(item, dict) else None
            if not isinstance(appearance, dict) or not appearance.get("self_avatar_source"):
                continue
            if appearance.get("self_avatar_source") != "VETO":
                for key in ("self_player_avatar", "display_name", "visual_identity",
                            "inspection_suppressed_reason"):
                    item.pop(key, None)
                item["inspectable"] = appearance.get("self_avatar_prev_inspectable", True)
            for key in ("self_player_avatar", "self_player_name", "self_player_guid",
                        "self_avatar_source", "self_avatar_vetoed", "self_avatar_prev_inspectable",
                        "self_avatar_evidence_role"):
                appearance.pop(key, None)
        identifier.update(state)
        for item in state.get("visual_candidates") or ():
            if isinstance(item, dict) and str(item.get("track_id")) in identifier.vetoed:
                appearance = dict(item.get("appearance") or {})
                appearance.update({"self_avatar_vetoed": True, "self_avatar_source": "VETO"})
                item["appearance"] = appearance
        state["self_avatar"] = identifier.snapshot()

    @staticmethod
    def _project_self_player_tracks(state: dict) -> None:
        """Name the likely local-avatar box without hiding overlapping pixels.

        Geometry remains a supported attention identity, not a visual claim
        that every subject in the same screen region is the player. Separate
        overlapping NPC/mob boxes remain untouched and fully inspectable.
        """
        player_name = str(state.get("character_name") or "").strip()
        player_guid = str(state.get("character_guid") or "").strip()
        by_track = {str(item.get("track_id")): item for item in state.get("visual_candidates") or ()
                    if isinstance(item, dict) and item.get("track_id") is not None}

        def symbol_really_above(subject: dict, symbol_track_id) -> bool:
            # Live 2026-09-30: a learned "symbol" sitting inside the top of the
            # player's own body box (head/hair, y 236-268 vs body top 231) formed
            # a SUPPORTED ABOVE group and kept a duplicate self track
            # inspectable, so SEEK parked the cursor on the player.  Only a
            # symbol whose box ends at or above the subject's top band can be
            # independent evidence for another unit.
            symbol = by_track.get(str(symbol_track_id))
            body, mark = (subject.get("bbox") or {}), ((symbol or {}).get("bbox") or {})
            if not all(isinstance(box.get(key), (int, float))
                       for box in (body, mark) for key in ("top", "bottom")):
                return True  # geometry unknown: keep the previous conservative behavior
            height = max(1., float(body["bottom"])-float(body["top"]))
            return float(mark["bottom"]) <= float(body["top"])+.12*height

        for candidate in state.get("visual_candidates") or ():
            if not isinstance(candidate, dict) or candidate.get("source") != "WORLD3D":
                continue
            appearance = (candidate.get("appearance")
                          if isinstance(candidate.get("appearance"), dict) else {})
            if (not appearance.get("self_avatar_suppression_hint")
                    or appearance.get("self_avatar_vetoed")
                    or candidate.get("self_player_avatar") is True):
                continue
            relations = candidate.get("visual_relations") or ()
            independently_anchored = any(
                isinstance(relation, dict)
                and str(relation.get("type") or "").upper() in {"ABOVE", "GROUP_MEMBER"}
                and str(relation.get("belief") or "").upper() == "SUPPORTED"
                and symbol_really_above(candidate, relation.get("symbol_track_id"))
                for relation in relations)
            visual_group = (candidate.get("visual_group")
                            if isinstance(candidate.get("visual_group"), dict) else {})
            labels = {str(label) for label in candidate.get("candidate_labels") or ()}
            group_symbols = [track for track in visual_group.get("member_track_ids") or ()
                             if str(track) != str(candidate.get("track_id"))]
            independently_anchored = bool(
                independently_anchored
                or (str(visual_group.get("belief") or "").upper() == "SUPPORTED"
                    and any(symbol_really_above(candidate, track) for track in group_symbols or (None,)))
                or any("overhead" in label or "quest_badge" in label for label in labels))
            if independently_anchored:
                # A distinct overhead cue is evidence for the overlapping NPC,
                # not the local player's identity. Keep that box inspectable.
                continue
            identity = {
                "kind": "SELF_PLAYER",
                "name": player_name or "Local player",
                "guid": player_guid or None,
                "belief": "SUPPORTED",
                "fact": False,
                "source": "ADDON_LOCAL_PLAYER+THIRD_PERSON_GEOMETRY",
            }
            candidate["self_player_avatar"] = True
            candidate["display_name"] = identity["name"]
            candidate["visual_identity"] = identity
            candidate["inspectable"] = False
            candidate["inspection_suppressed_reason"] = "SELF_PLAYER_AVATAR"
            appearance = dict(appearance)
            appearance.update({
                "self_player_avatar": True,
                "self_player_name": identity["name"],
                "self_player_guid": identity["guid"],
                "self_avatar_evidence_role": "IDENTIFIED_ATTENTION_SUPPRESS_ONLY",
            })
            candidate["appearance"] = appearance

    @staticmethod
    def _associate_visual_tracks(model: "WorldModel") -> None:
        subjects = [
            item for item in model.state.get("visual_candidates", [])
            if item.get("source") == "WORLD3D" and not is_self_avatar_box(item)
            and "subject" in str(item.get("detector_kind") or item.get("kind") or "")
            and number(item.get("x")) is not None and number(item.get("y")) is not None
        ]
        for anchor in model.mouseover_screen_anchors.values():
            if anchor.get("track_id") or not subjects:
                continue
            nearest = min(subjects, key=lambda item: math.hypot(
                float(item["x"]) - float(anchor["x"]),
                float(item["y"]) - float(anchor["y"])))
            distance = math.hypot(
                float(nearest["x"]) - float(anchor["x"]),
                float(nearest["y"]) - float(anchor["y"]))
            if distance <= .09:
                anchor.update({
                    "track_id": nearest.get("track_id"),
                    "bbox": _copy(nearest.get("bbox")),
                    "bbox_height_fraction": nearest.get("bbox_height_fraction"),
                    "track_confidence": nearest.get("confidence"),
                    "track_association": "CANDIDATE",
                    "association_distance": round(distance, 6),
                    "visual_signature": _copy(nearest.get("visual_signature")),
                })

    @staticmethod
    def screen_anchor_scene_valid(anchor: dict, state: dict) -> bool:
        """A GUID survives movement; its old screen pixel does not."""
        old_world = anchor.get("player_world_snapshot") or {}
        new_world = state.get("player_world_position") or {}
        ox, oy = number(old_world.get("x")), number(old_world.get("y"))
        nx, ny = number(new_world.get("x")), number(new_world.get("y"))
        if None not in (ox, oy, nx, ny) and math.hypot(nx - ox, ny - oy) > .75:
            return False
        old_map = anchor.get("player_map_snapshot") or {}
        new_map = state.get("position") or {}
        ox, oy = number(old_map.get("x")), number(old_map.get("y"))
        nx, ny = number(new_map.get("x")), number(new_map.get("y"))
        if None not in (ox, oy, nx, ny) and math.hypot(nx - ox, ny - oy) > .00075:
            return False
        old_heading = number(anchor.get("orientation_snapshot"))
        new_heading = number(state.get("orientation"))
        if None not in (old_heading, new_heading):
            delta = abs((new_heading - old_heading + math.pi) % math.tau - math.pi)
            if delta > .08:
                return False
        camera = state.get("camera_state") or {}
        old_yaw = number(anchor.get("camera_yaw_snapshot"))
        new_yaw = number(camera.get("yaw_estimate"))
        return not (None not in (old_yaw, new_yaw) and abs(new_yaw - old_yaw) > 8.)
