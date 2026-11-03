"""Evidence-gated orchestration for quest world-object interaction.

This policy owns no input and invents no object semantics.  It connects the
existing location, bounded visual-search and ``OBJECT_USE`` stages by carrying
the objective's explicit identity through active perception.  Addon mouseover
is the confirmation boundary; raw CV candidates remain UNKNOWN.
"""
from __future__ import annotations

from wowbot.runtime.entity_identity import check_entity_identity, identity_fields

import math

from .models import Proposal, number, words
from .quest_semantics import world_object_subjects


def _stems(text: str) -> list[str]:
    """Words without a plural ending: "cocoons" and "Thick Cocoon" meet."""
    stems = []
    for word in words(str(text or "")).split():
        stems.append(word[:-2] if word.endswith("es") and len(word) > 4 else
                     word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return stems


def name_matches(subjects, name) -> bool:
    name_stems = set(_stems(name))
    return bool(name_stems) and any(
        subject_stems and set(subject_stems) <= name_stems
        for subject_stems in (_stems(subject) for subject in subjects or ()))


# User 2026-10-06: the cocoon's quest_object_like track was ACTIVE at .25,
# but the former .55 gate discarded it.  This lower gate is ONLY for that
# learned object class; overhead/quest symbols retain their own thresholds.
# The box only authorizes approach/hover, never use without addon identity.
QUEST_OBJECT_MIN_CONFIDENCE = .20
QUEST_OBJECT_MIN_STABLE = 3


def quest_object_candidates(state: dict) -> list[dict]:
    """World3D boxes of the learned ``quest_object_outline_like`` class (user-
    labelled cocoons etc.), stable enough to walk to, largest first."""
    found = []
    for item in state.get("visual_candidates") or ():
        if not isinstance(item, dict) or item.get("source") != "WORLD3D":
            continue
        labels = {str(value).lower() for value in item.get("candidate_labels") or ()}
        appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
        labels.update(str(value).lower() for value in appearance.get("anchor_candidate_labels") or ())
        lifecycle = str(item.get("lifecycle") or item.get("track_state") or "ACTIVE").upper()
        if ("quest_object_like" not in labels or lifecycle in {"LOST", "REJECTED", "TERMINATED"}
                or (number(item.get("confidence")) or 0.) < QUEST_OBJECT_MIN_CONFIDENCE
                or (number(item.get("stable_frames")) or 0.) < QUEST_OBJECT_MIN_STABLE):
            continue
        found.append(item)
    return sorted(found, key=lambda item: -(number(item.get("bbox_height_fraction")) or 0.))


def only_object_objectives_open(state: dict) -> bool:
    """Every open objective of every unfinished quest is a game object.

    Live 2026-10-06 (Hrun's pit): the cocoon sweep stopped to hover another
    player's hunter pet, torches and spiders.  While only objects are
    wanted, a unit body without a quest symbol answers nothing; a finished
    quest (turn-in NPC) or any other objective type keeps units relevant.
    """
    found = False
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict):
            continue
        if quest.get("is_complete") is True:
            return False
        for objective in quest.get("objectives") or ():
            if not isinstance(objective, dict) or objective.get("is_complete"):
                continue
            if str(objective.get("raw_type") or "").lower() != "object":
                return False
            found = True
    return found


def open_object_objective(state: dict, quest_id=None) -> bool:
    """An unfinished game-object objective (raw type ``object``) is open."""
    for quest in state.get("active_quests") or ():
        if not isinstance(quest, dict) or quest.get("is_complete") is True:
            continue
        if quest_id is not None and str(quest.get("quest_id")) != str(quest_id):
            continue
        if any(isinstance(objective, dict) and not objective.get("is_complete")
               and str(objective.get("raw_type") or "").lower() == "object"
               for objective in quest.get("objectives") or ()):
            return True
    return False


def open_quest(state: dict, quest_id) -> bool:
    """The quest is in the log and not ready for turn-in."""
    return any(isinstance(quest, dict) and str(quest.get("quest_id")) == str(quest_id)
               and quest.get("is_complete") is not True
               for quest in state.get("active_quests") or ())


def object_objective_progress(state: dict, quest_id) -> float | None:
    """Current count of the quest's game-object objectives."""
    for quest in state.get("active_quests") or ():
        if isinstance(quest, dict) and str(quest.get("quest_id")) == str(quest_id):
            return sum(number(objective.get("current")) or 0.
                       for objective in quest.get("objectives") or ()
                       if isinstance(objective, dict)
                       and str(objective.get("raw_type") or "").lower() == "object")
    return None


def _objective_kinds_pending(state: dict, quest_id) -> bool:
    """The quest is open but its objectives carry no type yet.

    Live 2026-10-14 20:15:59: the first sample after accepting showed the
    objective with progress only (no description, no raw type); in that tick
    the separate TDB spawn MOVE to the pit bottom started.
    """
    for quest in state.get("active_quests") or ():
        if (isinstance(quest, dict) and str(quest.get("quest_id")) == str(quest_id)
                and quest.get("is_complete") is not True):
            objectives = [item for item in quest.get("objectives") or () if isinstance(item, dict)]
            return bool(objectives) and all(not item.get("raw_type") for item in objectives)
    return False


def quest_object_spawns(state: dict, quest_id) -> list[dict]:
    """The quest's TDB/learned GAMEOBJECT objective spawns in the player's
    instance, while one of its game-object objectives is open (or its
    objective types have not arrived yet)."""
    if not (open_object_objective(state, quest_id) or _objective_kinds_pending(state, quest_id)):
        return []
    reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
    instance = (state.get("player_world_position") or {}).get("instance_id")
    spawns, seen = [], set()
    for spawn in reference.get("spawn_candidates") or ():
        if not isinstance(spawn, dict) or spawn.get("entity_kind") != "GAMEOBJECT":
            continue
        x, y, z = number(spawn.get("x")), number(spawn.get("y")), number(spawn.get("z"))
        if (None in (x, y, z) or z == 0 or spawn.get("world_map_id") not in (None, instance)
                or (round(x), round(y), round(z)) in seen):
            continue
        seen.add((round(x), round(y), round(z)))
        spawns.append({"x": x, "y": y, "z": z, "hint": "spawn:GAMEOBJECT:" + str(spawn.get("spawn_id"))})
    return spawns


class ObjectInteractionFlow:
    """Compose locate -> local search -> validate -> use -> credit verify."""

    # Visual scale is diagnostic only for a hovered quest object: live 18:28
    # showed a .10-height cocoon that was usable.  Client range feedback,
    # followed by bounded forward pulses, owns the retry decision.
    OBJECT_READY_HEIGHT = .16

    @staticmethod
    def _hover_identity(state: dict) -> tuple[str, str] | None:
        from .tooltip_quest import effective_mouseover
        mouse = effective_mouseover(state)
        key = (str(mouse.get("quest_id") or ""),
               str(mouse.get("object_id") or mouse.get("name")
                   or mouse.get("unit_name") or "").casefold())
        return key if any(key) else None

    @staticmethod
    def _confirmed_hover_box(identity: dict, quest_id, state: dict,
                             boxes: list[dict]) -> dict | None:
        """Bind a current addon-confirmed object hover to one live visual box.

        A learned outline alone is never authority to walk toward scenery.
        The pointer, mouseover and box must agree in this same fresh view.
        """
        from .tooltip_quest import effective_mouseover
        now = number(state.get("monotonic_time"))
        mouse_at = number(state.get("mouseover_sample_time"))
        cursor_at = number(state.get("cursor_sample_time"))
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        mouse = effective_mouseover(state)
        if (None in (now, mouse_at, cursor_at, cx, cy)
                or not 0 <= now-mouse_at <= .75
                or not 0 <= now-cursor_at <= .75
                or abs(mouse_at-cursor_at) > .1
                or mouse.get("quest_related") is not True
                or str(mouse.get("quest_id")) != str(quest_id)
                or not ObjectInteractionFlow.mouseover_search_hint(identity, mouse)):
            return None
        for box in boxes:
            bx, by = number(box.get("x")), number(box.get("y"))
            observed = number(box.get("observed_at", box.get("last_seen")))
            if (None in (bx, by, observed)
                    or not 0 <= now-observed <= .8
                    or str(box.get("lifecycle") or box.get("track_state") or "ACTIVE").upper()
                    not in {"ACTIVE", "STABLE"}):
                continue
            width = number(box.get("bbox_width_fraction")) or 0.
            height = number(box.get("bbox_height_fraction")) or 0.
            if (abs(cx-bx) <= max(.025, width*.75)
                    and abs(cy-by) <= max(.025, height*.6)):
                return box
        return None

    def object_ready_height(self) -> float:
        return float(self.__dict__.get("_ready_height") or self.OBJECT_READY_HEIGHT)

    # Live 2026-10-14 14:03-14:08 (Hrun's pit): a cocoon's large box looked
    # "near" (bbox .39) 7.4 and 16 yd away.  The right-clicks got no credit,
    # then "out of range", and SEEK/MOVE cycled on the spot for a minute.
    # The 13:34 credit came from 4.3 yd.  A quest object with an exact TDB
    # spawn on our floor is walked to before it is clicked.
    USE_RANGE_YARDS = 4.
    SPOT_SEARCH_YARDS = 25.
    SPOT_FLOOR_YARDS = 8.
    SPOT_SPENT_YARDS = 6.
    SPOT_FORGET_SECONDS = 600.
    SPOT_EXHAUST_SECONDS = 20.

    def _spend_spot(self, state: dict, x: float, y: float, now: float) -> None:
        progress = {}
        for quest in state.get("active_quests") or ():
            if isinstance(quest, dict) and quest.get("quest_id") is not None:
                progress[str(quest["quest_id"])] = object_objective_progress(state, quest["quest_id"])
        spent = self.__dict__.setdefault("_spent_spot_log", [])
        spent.append((x, y, now, progress))
        del spent[:-32]

    def _spent_spots(self, state: dict, quest_id, now: float) -> list[tuple[float, float]]:
        """Credited/searched-out spots of this quest acceptance (a dropped
        progress means the quest was taken again: its objects count anew)."""
        current = object_objective_progress(state, quest_id)
        result = []
        for x, y, at, progress in self.__dict__.get("_spent_spot_log") or ():
            before = progress.get(str(quest_id))
            if (0 <= now-at <= self.SPOT_FORGET_SECONDS and before is not None
                    and current is not None and current >= before):
                result.append((x, y))
        return result

    def tdb_use_spot(self, state: dict, quest_id, player_z: float | None) -> dict | None:
        """The quest's nearest unspent TDB object spawn on the player's floor
        within ``SPOT_SEARCH_YARDS``, with its horizontal ``distance``; None
        if the floor is unknown or no such spawn exists (the old flow
        applies).  Horizontal: the approach MOVE stops 2.5 yd away in x/y,
        and the same floor is already required."""
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        now = number(state.get("monotonic_time"))
        if None in (px, py, player_z, now):
            return None
        spent = self._spent_spots(state, quest_id, now)
        best = None
        for spawn in quest_object_spawns(state, quest_id):
            flat = ((spawn["x"]-px)**2 + (spawn["y"]-py)**2) ** .5
            if (abs(spawn["z"]-player_z) > self.SPOT_FLOOR_YARDS or flat > self.SPOT_SEARCH_YARDS
                    or any(((spawn["x"]-x)**2 + (spawn["y"]-y)**2) ** .5 <= self.SPOT_SPENT_YARDS
                           for x, y in spent)):
                continue
            ranked = (flat*flat + (spawn["z"]-player_z)**2) ** .5
            if best is None or ranked < best[0]:
                best = (ranked, flat, spawn)
        if best is None:
            return None
        _, distance, spawn = best
        near = self.__dict__.setdefault("_spot_near_since", {})
        key = (round(spawn["x"]), round(spawn["y"]))
        if distance <= self.USE_RANGE_YARDS and state.get("is_in_combat"):
            near[key] = now                     # fighting here is not searching it out
        elif distance <= self.USE_RANGE_YARDS:
            since = near.setdefault(key, now)
            if now-since >= self.SPOT_EXHAUST_SECONDS:
                # Standing at the spot this long without credit: the object
                # is gone (opened earlier / despawned).  Try the next one.
                near.pop(key, None)
                self._spend_spot(state, spawn["x"], spawn["y"], now)
                return self.tdb_use_spot(state, quest_id, player_z)
        else:
            near.pop(key, None)
        return {**spawn, "distance": distance}

    # User 2026-10-14 (manual test): standing at a cocoon, facing it, the
    # Interact key opens it -- unless a (dead) mob or an NPC is near (the
    # soft-interact target jumps to it) or the character faces away.  The
    # addon never saw the cocoon as a soft target (723 samples), so this
    # press is gated by the exact TDB spot, the facing and "no unit soft
    # target"; the quest credit verifies it.
    INTERACT_KEY_FACING_RADIANS = .45
    INTERACT_KEY_ATTEMPT_SECONDS = 8.
    INTERACT_KEY_RETRY_SECONDS = 38.

    def interact_key_ready(self, state: dict, spot: dict) -> bool:
        if state.get("is_in_combat") or spot.get("distance", 99.) > self.USE_RANGE_YARDS:
            return False
        if any(isinstance(target, dict) and target.get("source_unit") == "softinteract"
               and target.get("unit_type") not in (None, "GAMEOBJECT")
               for target in state.get("soft_targets") or ()):
            return False                         # F7 would take that unit (corpse/NPC)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        facing = number(state.get("orientation"))
        now = number(state.get("monotonic_time"))
        if None in (px, py, facing, now):
            return False
        bearing = math.atan2(spot["y"]-py, spot["x"]-px)
        if abs((bearing-facing+math.pi) % math.tau - math.pi) > self.INTERACT_KEY_FACING_RADIANS:
            return False
        tried = self.__dict__.setdefault("_interact_key_tried", {})
        key = (round(spot["x"]), round(spot["y"]))
        at = tried.get(key)
        if at is None or now-at >= self.INTERACT_KEY_RETRY_SECONDS:
            tried[key] = now
            return True
        return now-at <= self.INTERACT_KEY_ATTEMPT_SECONDS   # the same attempt, not a new one

    # Server-confirmed quest objects (Ymir).  Live 2026-10-19 15:23-15:25
    # (Purge the Totems): the agent stood within 1 yd of three Harpy Totems
    # out of combat but had no hover/soft identity, so it never used one; the
    # one soft-target F7 (15:25:10.62) started the burn cast (SPELL_START
    # 22810) and a Harpy Snatcher's spell broke it 0.26 s later.
    # The server only reports objects in its visibility range; the pit's two
    # bottom cocoons are 82 / 96 yd from the 3rd one (live 2026-10-20).
    PACKET_SPOT_SEARCH_YARDS = 150.
    PACKET_USE_RANGE_YARDS = 3.5
    PACKET_FLOOR_YARDS = 3.
    PACKET_COMPETITOR_YARDS = 6.
    # Walked yards per yard of height: a lower level is reached down a ramp,
    # not straight through the floor (the pit spiral: ~80 yd walked for 24 yd
    # of descent, live 2026-10-20 09:36:42-09:36:58).
    PACKET_VERTICAL_WALK_FACTOR = 3.
    PACKET_PASSING_YARDS = 6.
    PACKET_SPENT_SECONDS = 60.
    # Live 2026-10-20 10:16-10:18 (Catapult Destruction): the walk aimed at
    # the catapult's centre ran into its model (supported_stuck 10:16:26,
    # 10:17:25) and Interact waited for 3.5 yd from that centre -- it fired
    # only when the user helped the character up onto the catapult.  A big
    # object's edge is learned where the walk stops making progress; F7 is
    # tried from there and later objects of that entry are approached only
    # that far.
    PACKET_EDGE_TRY_YARDS = 8.
    PACKET_EDGE_STALL_SECONDS = 1.2
    PACKET_EDGE_PROGRESS_YARDS = .3
    PACKET_EDGE_TURN_RADIANS = .15
    PACKET_EDGE_MARGIN_YARDS = .75
    PACKET_MAX_REACH_YARDS = 8.
    # Decorations never take the Interact key: generic, trap, spell focus.
    from .packet_entity_facts import PASSIVE_GO_TYPES as PACKET_PASSIVE_GO_TYPES

    def packet_approach_search(self):
        from .object_approach_search import ObjectApproachSearch
        if "_packet_approach_search" not in self.__dict__:
            self._packet_approach_search = ObjectApproachSearch()
        return self._packet_approach_search

    def packet_use_range(self, spot: dict) -> float:
        """Interact reach for this object: 3.5 yd, or its learned edge."""
        reach = self.__dict__.get("_packet_reach") or {}
        learned = max((reach.get(("guid", str(spot.get("guid")))) or 0.,
                       reach.get(("entry", str(spot.get("object_id")))) or 0.))
        return min(self.PACKET_MAX_REACH_YARDS, max(self.PACKET_USE_RANGE_YARDS, learned))

    def packet_stop_distance(self, spot: dict) -> float:
        """Where the approach stops: in front of a known big object's edge."""
        reach = self.packet_use_range(spot)
        return 2.0 if reach <= self.PACKET_USE_RANGE_YARDS else max(2.0, reach-1.)

    def _learn_packet_reach(self, guid, entry, distance: float) -> None:
        reach = self.__dict__.setdefault("_packet_reach", {})
        value = min(self.PACKET_MAX_REACH_YARDS, distance + self.PACKET_EDGE_MARGIN_YARDS)
        reach[("guid", str(guid))] = value
        if entry is not None:
            reach[("entry", str(entry))] = value

    def _forget_packet_reach(self, guid, entry) -> None:
        reach = self.__dict__.get("_packet_reach") or {}
        reach.pop(("guid", str(guid)), None)
        if entry is not None:
            reach.pop(("entry", str(entry)), None)

    def packet_use_spot(self, state: dict, quest_id, player_z: float | None
                        ) -> tuple[dict | None, bool]:
        """(nearest server-usable object of this quest, server data known).

        Known means the server reported at least one object of the quest's
        game-object objectives here; its usable/removed state then replaces
        the TDB spawn list and the spent-spot heuristics.
        """
        from .packet_entity_facts import hidden_object_sources, objective_objects
        objects = objective_objects(state, quest_id)
        linked_usable = open_quest(state, quest_id) and any(
            item.get("usable") and item.get("objective_id") not in (None, 0, "0") for item in objects)
        if not (open_object_objective(state, quest_id) or _objective_kinds_pending(state, quest_id)
                or (open_quest(state, quest_id) and hidden_object_sources(state, quest_id, described=True))
                or linked_usable):
            return None, False
        if not objects:
            return None, False
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return None, True
        now = number(state.get("monotonic_time"))
        spent = {guid for guid, at in (self.__dict__.get("_packet_spent") or {}).items()
                 if now is None or 0 <= now-at <= self.PACKET_SPENT_SECONDS}
        same_floor, other_floor = None, None
        for item in objects:
            if (not item["usable"] or item["guid"] in spent
                    or str(item.get("instance_id")) != str(position.get("instance_id"))):
                continue
            flat = math.hypot(item["x"]-px, item["y"]-py)
            dz = abs(item["z"]-player_z) if player_z is not None else 0.
            if flat > self.PACKET_SPOT_SEARCH_YARDS:
                continue
            if player_z is None or dz <= self.SPOT_FLOOR_YARDS:
                ranked = (math.hypot(flat, dz), flat, item)
                same_floor = min(same_floor or ranked, ranked, key=lambda row: row[0])
            else:
                ranked = (flat + self.PACKET_VERTICAL_WALK_FACTOR*dz, flat, item)
                other_floor = min(other_floor or ranked, ranked, key=lambda row: row[0])
        # Live 2026-10-20 09:27 (Who Lurks in the Pit): every Thick Cocoon was
        # 34-100 yd below the rim (exact server x,y,z, Activate set) and the
        # same-floor filter dropped all five, so only the visual search ran.
        # Another floor is a navmesh MOVE target with an exact height; the
        # layered navigation walks there.  Live 09:36:42: straight-line 3D
        # chose the bottom cocoon 61 yd under the one just used and walked
        # the spiral past the two between; height now costs walking yards.
        best = same_floor or other_floor
        if best is None:
            return None, True
        _, flat, item = best
        return {"x": item["x"], "y": item["y"], "z": item["z"], "distance": flat,
                "guid": item["guid"], "object_id": item.get("entry_id"),
                "hint": "packet:" + item["guid"], "source": "PACKET_GAMEOBJECT"}, True

    # Live 2026-10-23 00:40:58 (Library of Alexstrasza, 3/4 Books saved): the
    # server had forgotten the three unopened book chests 296-351 yd away (it
    # only sends what is near), but their exact positions were learned from
    # it earlier.  Walk to the nearest unopened one; near it the server names
    # it again and the server steps take over.
    REMEMBERED_SPOT_YARDS = 600.
    REMEMBERED_VISIT_YARDS = 30.
    REMEMBERED_DWELL_SECONDS = 4.

    def remembered_object_spot(self, state: dict, quest_id) -> dict | None:
        """Nearest learned/TDB spawn of the quest's hidden item-row objects
        not opened in this acceptance and not found gone at its place."""
        from .packet_entity_facts import hidden_object_sources, objective_objects
        entries = {entry for _objective, entry in hidden_object_sources(state, quest_id)}
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        now = number(state.get("monotonic_time"))
        if not entries or not open_quest(state, quest_id) or None in (px, py, now):
            return None
        used = self._used_object_entries(state, quest_id)
        unreachable = {key for key, until in (self.__dict__.get("_far_unreachable") or {}).items()
                       if now < until}
        visible = {str(item["entry_id"]): item for item in objective_objects(state, quest_id)}
        reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
        arrived = self.__dict__.setdefault("_remembered_arrival", {})
        best = None
        for spawn in reference.get("spawn_candidates") or ():
            if not isinstance(spawn, dict) or spawn.get("entity_kind") != "GAMEOBJECT":
                continue
            entry = str(spawn.get("entry") or spawn.get("object_id") or "")
            x, y, z = number(spawn.get("x")), number(spawn.get("y")), number(spawn.get("z"))
            if (entry not in entries or entry in used or None in (x, y, z)
                    or ("spawn", str(quest_id), entry) in unreachable
                    or spawn.get("world_map_id") not in (None, position.get("instance_id"))):
                continue
            flat = math.hypot(x-px, y-py)
            key = (str(quest_id), entry)
            if flat <= self.REMEMBERED_VISIT_YARDS and not (visible.get(entry) or {}).get("usable"):
                # Here, and the server shows no usable object of it: opened
                # earlier or despawned.  Never come back for it.
                since = arrived.setdefault(key, now)
                if now-since >= self.REMEMBERED_DWELL_SECONDS:
                    self._note_used_object_entry(state, quest_id, entry)
                continue
            arrived.pop(key, None)
            if flat <= self.REMEMBERED_SPOT_YARDS and (best is None or flat < best[0]):
                best = (flat, entry, x, y, z, spawn)
        if best is None:
            return None
        flat, entry, x, y, z, spawn = best
        self._far_pending = ("spawn", str(quest_id), entry)
        return {"x": x, "y": y, "z": z, "distance": flat, "object_id": entry,
                "hint": "spawn:GAMEOBJECT:" + str(spawn.get("spawn_id")),
                "source": str(spawn.get("source") or "SPAWN")}

    # User 2026-10-23: if it is not there and no fresh position comes from
    # the server, walk the quest POI zone; the server sends fresh data as we
    # go.  Server mode has no screen sweep, so this one walks: the next cell
    # is the nearest POI-polygon cell not yet within sight of the trail (the
    # server sent the book chests 150-200 yd away).  Two passes at most.
    SWEEP_SIGHT_YARDS = 80.
    SWEEP_TRAIL_YARDS = 20.
    SWEEP_PASSES = 2
    FAR_UNREACHABLE_SECONDS = 300.

    def server_sweep_cell(self, state: dict, quest_id) -> dict | None:
        from .visual_search_planning import VisualSearchPlanningPolicy
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        now = number(state.get("monotonic_time"))
        quest = next((item for item in state.get("active_quests") or ()
                      if isinstance(item, dict) and str(item.get("quest_id")) == str(quest_id)), None)
        if quest is None or quest.get("is_complete") is True or None in (px, py, now):
            return None
        cells = VisualSearchPlanningPolicy.objective_poi_points(state, str(quest_id), quest)
        if not cells:
            return None
        sweep = self.__dict__.setdefault("_server_sweeps", {}).setdefault(
            str(quest_id), {"trail": [], "passes": 0})
        trail = sweep["trail"]
        if not trail or math.hypot(trail[-1][0]-px, trail[-1][1]-py) >= self.SWEEP_TRAIL_YARDS:
            trail.append((px, py))
            del trail[:-400]
        unreachable = {key for key, until in (self.__dict__.get("_far_unreachable") or {}).items()
                       if now < until}

        def open_cells():
            return [cell for cell in cells
                    if ("cell", str(quest_id), round(cell["x"]), round(cell["y"])) not in unreachable
                    and not any(math.hypot(cell["x"]-x, cell["y"]-y) <= self.SWEEP_SIGHT_YARDS
                                for x, y in sweep["trail"])]
        candidates = open_cells()
        if not candidates and sweep["passes"]+1 < self.SWEEP_PASSES:
            sweep["passes"] += 1               # the whole zone was seen: one more pass
            sweep["trail"] = [(px, py)]
            candidates = open_cells()
        if not candidates:
            return None
        cell = min(candidates, key=lambda item: math.hypot(item["x"]-px, item["y"]-py))
        self._far_pending = ("cell", str(quest_id), round(cell["x"]), round(cell["y"]))
        return {**cell, "distance": math.hypot(cell["x"]-px, cell["y"]-py)}

    def _note_far_failure(self, last: dict, now) -> None:
        """A learned place or sweep cell whose walk failed is skipped a while."""
        pending = self.__dict__.get("_far_pending")
        if (pending is None or now is None or last.get("skill") != "MOVE" or last.get("outcome") != "FAILURE"
                or last.get("purpose") not in {"LOCATE_REMEMBERED_QUEST_OBJECT", "SERVER_ZONE_SWEEP"}):
            return
        self.__dict__.setdefault("_far_unreachable", {})[pending] = now + self.FAR_UNREACHABLE_SECONDS
        self._far_pending = None

    @staticmethod
    def _quest_progress(state: dict, quest_id) -> float | None:
        for quest in state.get("active_quests") or ():
            if isinstance(quest, dict) and str(quest.get("quest_id")) == str(quest_id):
                return sum(number(objective.get("current")) or 0.
                           for objective in quest.get("objectives") or () if isinstance(objective, dict))
        return None

    def _note_used_object_guid(self, state: dict, guid: str) -> None:
        """A credited object: its entry is spent for every open quest whose
        hidden item rows come from it (GameObject-0-..-<entry>-<low>)."""
        from .packet_entity_facts import hidden_object_sources
        entry = ((state.get("packet_entities") or {}).get(guid) or {}).get("entry_id")
        parts = guid.split("-")
        if entry is None and len(parts) == 7 and parts[0] == "GameObject":
            entry = parts[5]
        if entry is None:
            return
        for quest in state.get("active_quests") or ():
            if not isinstance(quest, dict) or quest.get("quest_id") is None:
                continue
            if str(entry) in {item for _objective, item in hidden_object_sources(state, quest["quest_id"])}:
                self._note_used_object_entry(state, quest["quest_id"], entry)

    def _note_used_object_entry(self, state: dict, quest_id, entry) -> None:
        used = self.__dict__.setdefault("_used_object_entry_log", {})
        used.setdefault(str(quest_id), {})[str(entry)] = self._quest_progress(state, quest_id)

    def _used_object_entries(self, state: dict, quest_id) -> set[str]:
        """Entries opened/found gone since this acceptance (lower progress =
        the quest was taken again: its objects count anew)."""
        current = self._quest_progress(state, quest_id)
        rows = (self.__dict__.get("_used_object_entry_log") or {}).get(str(quest_id)) or {}
        return {entry for entry, before in rows.items()
                if before is None or current is None or current >= before}

    def packet_interact_ready(self, state: dict, spot: dict, player_z: float | None, *, reach=None) -> str:
        """READY, or why the Interact key may not use this server object yet.

        Identity comes from the server (GUID, objective, Activate flag); the
        press itself still needs what the user's manual test showed: close,
        facing it, no unit soft target and nothing else nearer.  Never in
        combat: an attacker interrupts the use cast (live 15:25:11.050).
        """
        if state.get("is_in_combat"):
            return "IN_COMBAT"
        from .packet_entity_facts import entity, game_object_use_candidate
        value = entity(state, spot.get("guid"))
        if value is not None and not game_object_use_candidate(state, value):
            return "NOT_INTERACTABLE"
        if self.packet_approach_search().blocked(state, spot):
            return "REPOSITION"
        from wowbot.runtime.skill_identity import check_interaction_recipient
        soft = next((row for row in state.get("soft_targets") or () if isinstance(row, dict)
                     and str(row.get("source_unit") or "").casefold() == "softinteract"), None)
        recipient_block = None
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        facing = number(state.get("orientation"))
        # Recipient identity proves which object F7 would address, not that
        # we are facing it after passing its anchor (live fragment pickup).
        facing_ready = None not in (px, py, facing) and (
            math.hypot(spot["x"]-px, spot["y"]-py) < 1.
            or abs((math.atan2(spot["y"]-py, spot["x"]-px)-facing+math.pi) % math.tau-math.pi)
            <= self.INTERACT_KEY_FACING_RADIANS)
        if soft and soft.get("guid"):
            if str(soft["guid"]) != str(spot.get("guid")):
                recipient_block = "OTHER_OBJECT_NEARER" if str(soft["guid"]).startswith("GameObject-") else "UNIT_SOFT_TARGET"
            now = number(state.get("monotonic_time"))
            if (str(soft["guid"]) == str(spot.get("guid")) and str(soft["guid"]).startswith("GameObject-") and now is not None
                    and check_interaction_recipient({"guid": spot["guid"]}, state, now)):
                # The client has selected this exact huge object's physical
                # interact surface; its centre need not be within 2-3 yards.
                from .destination_distance import observed_height
                measured_z = observed_height(position)
                if measured_z is None and position.get("z_known") is True and position.get("z_estimated") is not True:
                    measured_z = number(position.get("z"))
                # An inferred MMAP floor cannot veto a fresh exact client
                # recipient. At the forge edge it snapped 207 -> 202.9 while
                # the client still named the forge, so MOVE kept pushing and
                # recovered away instead of handing off to use. A measured
                # contradictory floor remains a hard rejection.
                if measured_z is not None and abs(spot["z"]-measured_z) > self.PACKET_FLOOR_YARDS:
                    return "OTHER_FLOOR"
                return "READY" if facing_ready else "NO_POSE" if None in (px, py, facing) else "NOT_FACING"
            if recipient_block is None:
                recipient_block = "STALE_RECIPIENT"
        limit = self.packet_use_range(spot) if reach is None else min(self.PACKET_MAX_REACH_YARDS, max(0., reach))
        if spot.get("distance", 99.) > limit:
            return "OUT_OF_RANGE"
        if player_z is not None and abs(spot["z"]-player_z) > self.PACKET_FLOOR_YARDS:
            return "OTHER_FLOOR"
        if recipient_block is not None:
            return recipient_block
        if any(isinstance(target, dict) and str(target.get("source_unit") or "").casefold() == "softinteract"
               and target.get("unit_type") not in (None, "GAMEOBJECT")
               for target in state.get("soft_targets") or ()):
            return "UNIT_SOFT_TARGET"               # F7 would take that unit (corpse/NPC)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        facing = number(state.get("orientation"))
        if None in (px, py, facing):
            return "NO_POSE"
        from .packet_entity_facts import game_objects_near
        entities = state.get("packet_entities") or {}
        if any(other["guid"] != spot["guid"]
               and ((entities.get(other["guid"]) or {}).get("info") or {}).get("go_type")
               not in self.PACKET_PASSIVE_GO_TYPES
               and math.hypot(other["x"]-px, other["y"]-py) <= spot["distance"]+.5
               for other in game_objects_near(state, px, py,
                                              max(self.PACKET_COMPETITOR_YARDS, spot["distance"]+.5))):
            return "OTHER_OBJECT_NEARER"
        if spot["distance"] >= 1.:
            bearing = math.atan2(spot["y"]-py, spot["x"]-px)
            if abs((bearing-facing+math.pi) % math.tau - math.pi) > self.INTERACT_KEY_FACING_RADIANS:
                return "NOT_FACING"
        return "READY"

    def _edge_reached(self, state: dict, guid: str, player_z=None) -> dict | None:
        """The walk to this object has stopped getting closer within reach of
        a big object's edge (not while turning): learn that reach, hand off."""
        from .packet_entity_facts import best_position, entity
        value = entity(state, guid)
        point = best_position(value) if value is not None else None
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        facing, now = number(state.get("orientation")), number(state.get("monotonic_time"))
        if point is None or None in (px, py, now):
            return None
        layer_z = number(player_z) if player_z is not None else number(position.get("z"))
        if layer_z is None or abs(point["z"]-layer_z) > self.PACKET_FLOOR_YARDS:
            self._edge_track = None
            return None
        if self.packet_approach_search().blocked(state, {**point, "guid": guid}):
            self._edge_track = None
            return {"reason": "server_quest_object_edge_rejected", "kind": "SERVER_QUEST_OBJECT_REPOSITION",
                    "guid": guid}
        distance = math.hypot(point["x"]-px, point["y"]-py)
        track = self.__dict__.get("_edge_track")
        if not self.PACKET_USE_RANGE_YARDS < distance <= self.PACKET_EDGE_TRY_YARDS:
            self._edge_track = None
            return None
        turned = (track is not None and facing is not None and track.get("facing") is not None
                  and abs((facing-track["facing"]+math.pi) % math.tau - math.pi) > self.PACKET_EDGE_TURN_RADIANS)
        if (track is None or track["guid"] != guid or turned
                or distance < track["best"]-self.PACKET_EDGE_PROGRESS_YARDS):
            self._edge_track = {"guid": guid, "best": distance, "since": now, "facing": facing}
            return None
        if now-track["since"] < self.PACKET_EDGE_STALL_SECONDS:
            return None
        self._edge_track = None
        if str(value.get("entry_id")) in self.__dict__.get("_small_entries", set()):
            # Live 2026-11-02 (Fresh Dirt): a walk stalled 7.8 yd away on the
            # terrain was learned as a big object's edge; F7 there failed
            # OUT_OF_RANGE again and again.  An entry whose learned edge
            # failed on range is small: approach it to the normal 3.5 yd.
            return None
        self._learn_packet_reach(guid, value.get("entry_id"), distance)
        return {"reason": "server_quest_object_edge_reached", "kind": "SERVER_QUEST_OBJECT_EDGE",
                "guid": guid, "distance": round(distance, 2)}

    def object_move_handoff(self, state: dict, params: dict, player_z: float | None) -> dict | None:
        """Why a running walk to one quest object should yield to the planner.

        Live 2026-10-20 09:36:42-09:37:26 (Who Lurks in the Pit): the MOVE to
        the bottom cocoon passed the 2nd one at 4.5 yd and the 3rd at 2 yd,
        each under the cursor, and walked on: nothing stops a MOVE before it
        arrives.  Only a handoff the planner turns into a use or a shorter
        walk is returned (it ranks with the same rule), never a loop.
        """
        quest_id = params.get("quest_id")
        if (params.get("purpose") != "APPROACH_QUEST_OBJECT_SPAWN" or quest_id is None
                or state.get("is_in_combat")):
            return None
        guid = params.get("server_entity_guid")
        if guid:
            from .packet_entity_facts import go_flags_usable
            target = (state.get("packet_entities") or {}).get(str(guid))
            flags = ((target or {}).get("dynamic_flags") or {}).get("value")
            if isinstance(target, dict) and (target.get("removed")
                                             or type(flags) is int and not go_flags_usable(flags)):
                return {"reason": "server_quest_object_spent", "kind": "SERVER_QUEST_OBJECT_CHANGED",
                        "guid": str(guid)}
            from .packet_entity_facts import best_position, game_object_use_candidate
            point = best_position(target) if target else None
            if target and not game_object_use_candidate(state, target):
                return {"reason": "server_quest_object_not_interactable", "kind": "SERVER_QUEST_OBJECT_CHANGED",
                        "guid": str(guid)}
            # A huge object's usable surface may be >8 yd from its centre.
            # The exact fresh client recipient stops the MOVE immediately;
            # a mere collision at that distance never authorizes F7.
            soft = next((row for row in state.get("soft_targets") or () if isinstance(row, dict)
                         and str(row.get("source_unit") or "").casefold() == "softinteract"), {})
            position = state.get("player_world_position") or {}
            px, py = number(position.get("x")), number(position.get("y"))
            if point is not None and None not in (px, py) and str(soft.get("guid")) == str(guid):
                spot = {**point, "guid": str(guid), "distance": math.hypot(point["x"]-px, point["y"]-py)}
                if self.packet_interact_ready(state, spot, player_z) == "READY":
                    return {"reason": "server_quest_object_ready", "kind": "SERVER_QUEST_OBJECT_READY",
                            "guid": str(guid)}
            if params.get("object_approach_probe"):
                return None  # finish the navmesh probe; do not relearn the rejected edge
            edge = self._edge_reached(state, str(guid), player_z)
            if edge is not None:
                return edge
        if player_z is None:
            return None
        spot, known = self.packet_use_spot(state, quest_id, player_z)
        if known:
            if (spot is not None and spot["guid"] != guid
                    and spot["distance"] <= self.PACKET_PASSING_YARDS
                    and abs(spot["z"]-player_z) <= self.PACKET_FLOOR_YARDS):
                return {"reason": "server_quest_object_passing", "kind": "SERVER_QUEST_OBJECT_PASSING",
                        "guid": spot["guid"], "distance": round(spot["distance"], 2)}
            return None
        # No server data: the cursor is on an object the client's quest
        # tooltip certifies, at an unspent spawn in use range -- the planner
        # then right-clicks it instead of walking on to the next spawn.
        from .tooltip_quest import effective_mouseover
        now = number(state.get("monotonic_time"))
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (None in (px, py, now)
                or not self.tooltip_certified({}, effective_mouseover(state), state, quest_id, player_z)):
            return None
        spent = self._spent_spots(state, quest_id, now)
        if any(math.hypot(spawn["x"]-px, spawn["y"]-py) <= self.USE_RANGE_YARDS
               and abs(spawn["z"]-player_z) <= self.SPOT_FLOOR_YARDS
               and not any(math.hypot(spawn["x"]-x, spawn["y"]-y) <= self.SPOT_SPENT_YARDS for x, y in spent)
               for spawn in quest_object_spawns(state, quest_id)):
            return {"reason": "quest_object_tooltip_hovered", "kind": "QUEST_OBJECT_HOVERED"}
        return None

    @staticmethod
    def objective_object_names(identity: dict, state: dict, quest_id, objective_id=None) -> list[str]:
        """The objective's object names: its own identity, else the quest's
        TDB game-object objectives (live 2026-10-20: 55881:0 carried no
        object name at all while the reference said "Harpy Totem")."""
        names = [value for value in (identity.get("tdb_object_name"),
                                     *(identity.get("expected_tooltips") or ())) if value]
        reference = ((state.get("reference_knowledge") or {}).get("quests") or {}).get(str(quest_id)) or {}
        index = str(objective_id).split(":", 1)[1] if objective_id and ":" in str(objective_id) else None
        for row in reference.get("objectives") or ():
            if not isinstance(row, dict) or row.get("credit_kind") != "GAMEOBJECT":
                continue
            if index is not None and str(row.get("order", row.get("storage_index"))) != index:
                continue
            name = (row.get("object_template") or {}).get("name")
            if name:
                names.append(str(name))
        return list(dict.fromkeys(names))

    def tooltip_certified(self, identity: dict, mouse: dict, state: dict, quest_id,
                          player_z: float | None) -> bool:
        """The hovered object is this objective's, by the client's quest tooltip.

        Needs the shared QUEST_OBJECT_TOOLTIP rule (no unit GUID, no object
        ID, quest line of this quest, objective object name) and, when the
        quest's object spawns are known, one of them within use range: the
        click is never sent from afar ("You are too far away", live 08:17).
        """
        from wowbot.runtime.skill_identity import QUEST_OBJECT_TOOLTIP, quest_object_tooltip_matches
        params = {"identity_certification": QUEST_OBJECT_TOOLTIP, "quest_ids": [quest_id],
                  "expected_tooltips": self.objective_object_names(identity, state, quest_id)}
        if not quest_object_tooltip_matches(params, mouse):
            return False
        spawns = quest_object_spawns(state, quest_id)
        if not spawns:
            return True
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if px is None or py is None:
            return False
        # Unknown floor: the 2D range still keeps the click near a spawn.
        return any(math.hypot(spawn["x"]-px, spawn["y"]-py) <= self.USE_RANGE_YARDS
                   and (player_z is None or abs(spawn["z"]-player_z) <= self.SPOT_FLOOR_YARDS)
                   for spawn in spawns)

    def object_at_hand(self, state: dict, quest_id, player_z: float | None) -> bool | None:
        """Is a usable quest object near on our floor?  None: unknown (no
        spawn data or no floor) -- callers keep their former behaviour."""
        if player_z is None or not quest_object_spawns(state, quest_id):
            return None
        return self.tdb_use_spot(state, quest_id, player_z) is not None

    def note_result(self, last_result: dict | None, state: dict) -> None:
        """Learn once per finished action from an object use's range error."""
        last = last_result if isinstance(last_result, dict) else {}
        action = last.get("action_id")
        if not action or action == self.__dict__.get("_noted_action"):
            return
        self._noted_action = action
        self._note_far_failure(last, number(state.get("monotonic_time")))
        if (last.get("skill") == "OBJECT_USE"
                and "range" in str(last.get("reason") or "").lower()):
            identity = self._hover_identity(state)
            if identity is not None and identity != self.__dict__.get("_range_failure_identity"):
                self._range_failure_count = 0
                self._range_failure_identity = identity
            self._range_failure_count = min(3, int(self.__dict__.get("_range_failure_count") or 0)+1)
            height = max((number(box.get("bbox_height_fraction")) or 0.
                          for box in quest_object_candidates(state)), default=0.)
            self._ready_height = min(.6, max(self.object_ready_height()*1.25, height*1.3))
            self._range_blocked_at = number(state.get("monotonic_time"))
            cursor = state.get("cursor_position") or {}
            position = state.get("player_world_position") or {}
            self._range_blocked_cursor = (number(cursor.get("nx")), number(cursor.get("ny")))
            self._range_blocked_position = (position.get("instance_id"),
                                            number(position.get("x")), number(position.get("y")))
        elif (last.get("skill") == "OBJECT_USE"
              and "line_of_sight" in str(last.get("reason") or "").lower()):
            cursor = state.get("cursor_position") or {}
            position = state.get("player_world_position") or {}
            self._los_blocked_cursor = (number(cursor.get("nx")), number(cursor.get("ny")))
            self._los_blocked_position = (position.get("instance_id"),
                                          number(position.get("x")), number(position.get("y")))
        elif (last.get("skill") in {"VISUAL_APPROACH", "MOVE"}
              and last.get("outcome") == "SUCCESS"):
            self._range_blocked_at = None          # movement, not hover, permits retry
        if (last.get("skill") == "OBJECT_USE" and last.get("outcome") == "FAILURE"
                and last.get("object_guid")
                and any(token in str(last.get("reason") or "").lower()
                        for token in ("credit", "range", "far", "line_of_sight"))):
            value = (state.get("packet_entities") or {}).get(str(last["object_guid"])) or {}
            reason = str(last.get("reason") or "").lower()
            if ("range" in reason or "far" in reason) and value.get("entry_id") is not None:
                if self.packet_use_range({"guid": last["object_guid"], "object_id": value.get("entry_id")})                         > self.PACKET_USE_RANGE_YARDS:
                    self.__dict__.setdefault("_small_entries", set()).add(str(value["entry_id"]))
            self.packet_approach_search().reject(state, last["object_guid"], reason=reason)
            self._forget_packet_reach(last["object_guid"], value.get("entry_id"))
        if last.get("skill") == "OBJECT_USE" and last.get("outcome") == "SUCCESS":
            self._los_blocked_cursor = None
            self._range_blocked_at = None
            self._range_failure_count = 0
            self._range_failure_identity = None
            cursor = state.get("cursor_position") or {}
            self._credited = (number(state.get("monotonic_time")),
                              number(cursor.get("nx")), number(cursor.get("ny")))
            position = state.get("player_world_position") or {}
            px, py = number(position.get("x")), number(position.get("y"))
            now = number(state.get("monotonic_time"))
            if None not in (px, py, now):
                # The credited object stood within use range of here.
                self._spend_spot(state, px, py, now)
            if last.get("object_guid") and now is not None:
                # Live 2026-10-20 09:36:39.5: the quest log credited the cocoon
                # 0.7 s before the server removed it, and the same tick pressed
                # Interact on it again.  A credited server object is spent.
                self.__dict__.setdefault("_packet_spent", {})[str(last["object_guid"])] = now
                self._note_used_object_guid(state, str(last["object_guid"]))
            lock = self.__dict__.get("lock")
            if lock is not None and lock.active:
                lock.release("credited", now if now is not None else 0., spent=True)

    CREDITED_HOLD_SECONDS = 3.
    CREDITED_CURSOR_RADIUS = .04

    def just_credited(self, state: dict) -> bool:
        """The object under the unmoved cursor was just credited.

        Live 2026-10-07 12:06: the FAST quest digest verified the 5th cocoon;
        the paged snapshot still showed 4/5 and the tooltip still named the
        cocoon, so a second OBJECT_USE right-clicked the freed prisoner
        ("Invalid target")."""
        credited = self.__dict__.get("_credited")
        now = number(state.get("monotonic_time"))
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if not credited or None in (credited[0], now, cx, cy):
            return False
        at, x, y = credited
        near = x is None or y is None or abs(cx-x) + abs(cy-y) <= self.CREDITED_CURSOR_RADIUS
        return 0 <= now-at <= self.CREDITED_HOLD_SECONDS and near

    def range_blocked(self, state: dict) -> bool:
        """A range error remains until movement or a different object cue."""
        blocked = number(self.__dict__.get("_range_blocked_at"))
        if blocked is None:
            return False
        original_cursor = self.__dict__.get("_range_blocked_cursor") or (None, None)
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if (None not in (*original_cursor, cx, cy)
                and abs(cx-original_cursor[0])+abs(cy-original_cursor[1]) > .06):
            # Camera movement slides the same cocoon under a new cursor
            # coordinate.  A new coordinate alone is not evidence that the
            # client's range error no longer applies to this object.
            current_identity = self._hover_identity(state)
            failed_identity = self.__dict__.get("_range_failure_identity")
            if (current_identity is not None and failed_identity is not None
                    and current_identity != failed_identity):
                self._range_blocked_at = None
                return False
        previous = self.__dict__.get("_range_blocked_position") or (None, None, None)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (previous[0] is not None and position.get("instance_id") is not None
                and position.get("instance_id") != previous[0]):
            self._range_blocked_at = None
            return False
        if (None not in (previous[1], previous[2], px, py)
                and (px-previous[1])**2+(py-previous[2])**2 >= 4.):
            self._range_blocked_at = None
            return False
        return True

    def line_of_sight_blocked(self, state: dict) -> bool:
        """Do not retry the same obstructed click without a changed position/cue.

        Moving to a different object (cursor) or walking at least two yards
        permits a fresh attempt; repeated hover at the same wall does not.
        """
        original = self.__dict__.get("_los_blocked_cursor")
        if original is None:
            return False
        cursor = state.get("cursor_position") or {}
        cx, cy = number(cursor.get("nx")), number(cursor.get("ny"))
        if None not in (*original, cx, cy) and abs(cx-original[0])+abs(cy-original[1]) > .06:
            self._los_blocked_cursor = None
            return False
        previous = self.__dict__.get("_los_blocked_position") or (None, None, None)
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        if (previous[0] is not None and position.get("instance_id") is not None
                and position.get("instance_id") != previous[0]):
            self._los_blocked_cursor = None
            return False
        if (None not in (previous[1], previous[2], px, py)
                and position.get("instance_id") == previous[0]
                and (px-previous[1])**2+(py-previous[2])**2 >= 4.):
            self._los_blocked_cursor = None
            return False
        return True

    @staticmethod
    def expected_identity(objective) -> dict:
        target = dict(getattr(objective, "target_object", {}) or {})
        raw = getattr(objective, "raw", {}) or {}
        subjects = world_object_subjects({**raw, "description": getattr(objective, "description", "")})
        if raw.get('tdb_object_name'):
            subjects = list(dict.fromkeys([raw['tdb_object_name'], *subjects]))
        return {
            "object_id": target.get("object_id") or raw.get('tdb_object_id'),
            "item_id": target.get("item_id"),
            "expected_tooltips": subjects,
            "tdb_object_name": raw.get('tdb_object_name'),
        }

    @staticmethod
    def mouseover_search_hint(identity: dict, mouseover: dict) -> bool:
        """A bounded aiming/approach hint only, never permission to use.

        Missing public IDs do not make scenery certain. A currently named
        object can still guide a hover probe while waiting for numeric proof.
        Any explicit contradictory ID/GUID, however, rejects even the hint.
        """
        wanted, actual = identity_fields(identity), identity_fields(mouseover)
        shared = {key: value for key, value in wanted.items() if key in actual}
        if shared and not check_entity_identity(shared, mouseover):
            return False
        if wanted and check_entity_identity(wanted, mouseover):
            return True
        name = mouseover.get("unit_name") or mouseover.get("name") or str(mouseover.get("tooltip") or "").split("~", 1)[0]
        subjects = [*identity.get("expected_tooltips", ()), identity.get("tdb_object_name")]
        return name_matches(subjects, name)

    @staticmethod
    def mouseover_matches(identity: dict, mouseover: dict) -> bool:
        """Accept explicit IDs first; textual identity only when no ID exists."""
        explicit = identity_fields(identity)
        if explicit:
            return bool(check_entity_identity(explicit, mouseover))
        # A textual subject narrows search; input additionally requires a
        # current public GUID/object ID. Never certify a name-only tooltip.
        observed = identity_fields(mouseover)
        if not observed or not check_entity_identity(observed, mouseover):
            return False
        tooltip = f" {words(str(mouseover.get('tooltip') or '')).strip()} "
        subjects = [words(str(value)).strip() for value in identity.get("expected_tooltips") or ()]
        name = mouseover.get("unit_name") or mouseover.get("name")
        if tooltip.strip():
            return bool(any(value and f" {value} " in tooltip for value in subjects)
                        or name_matches(subjects, name))
        # The FAST lane carries the current structured game-object name even
        # when the long tooltip is dropped to fit one pixel-grid packet.
        return mouseover.get("quest_related") is True and name_matches(subjects, name)

    @staticmethod
    def quest_mouseover_matches(identity: dict, mouseover: dict,
                                state: dict, quest_id) -> bool:
        """Identity plus a live link to this open quest, not name alone."""
        if quest_id is None or not ObjectInteractionFlow.mouseover_matches(identity, mouseover):
            return False
        # An explicit current object ID is stronger than a quest-title
        # tooltip, which the addon may omit on its narrow FAST packet.
        if (identity.get('object_id') is not None
                and mouseover.get('object_id') not in (None, '', 0, '0')):
            return True
        if not identity.get('tdb_object_name'):
            # A tool object (the campfire of "Cook the meat", credit = an
            # item) never carries a quest line; only an object that is itself
            # the TDB GAMEOBJECT credit loses it once used for this character.
            return bool(mouseover.get("tooltip")
                        or str(mouseover.get("quest_id")) == str(quest_id))
        if (mouseover.get('quest_related') is True
                and str(mouseover.get('quest_id')) == str(quest_id)):
            return True
        from .tooltip_quest import tooltip_quest_id
        inferred = tooltip_quest_id(mouseover, state)
        return inferred is not None and str(inferred) == str(quest_id)

    @staticmethod
    def soft_target(identity: dict, state: dict) -> dict | None:
        """The soft-interact game object (addon 0.9.57) when it is the objective's."""
        for target in state.get("soft_targets") or ():
            if not isinstance(target, dict) or target.get("unit_type") != "GAMEOBJECT":
                continue
            if str(target.get("source_unit") or "").casefold() != "softinteract":
                continue
            if (ObjectInteractionFlow.mouseover_search_hint(identity, target)
                    and identity_fields(target)
                    and check_entity_identity(identity_fields(target), target)):
                return target
        return None

    def propose_object_steps(self, objective, record, state: dict) -> list[Proposal]:
        """User 2026-10-06 (cocoons): the learned quest-object box is seen,
        the soft-interact target or the hovered tooltip is the object: walk
        to it, hover it, use it -- above the zone sweep and the dot walk."""
        identity = self.expected_identity(objective)
        quest_ids = [getattr(record, "quest_id", None) or objective.objective_id.split(":", 1)[0]]
        steps = []
        boxes = quest_object_candidates(state)
        if self.line_of_sight_blocked(state):
            return []
        confirmed = self._confirmed_hover_box(identity, quest_ids[0], state, boxes)
        # Live 2026-10-07 12:58: the right-click returned "You are too far
        # away"; SEEK then hovered the same .10-height cocoon repeatedly
        # without moving.  A *client* range error requires an approach.
        # Box height alone is not a range test: the 18:28 live run had a
        # correctly named, hovered small box that the user could use.
        # Let the normal fresh-hover OBJECT_USE try once before any range
        # error; its verified failure can then bind this approach to a box.
        from .tooltip_quest import effective_mouseover
        mouse = effective_mouseover(state)
        from .server_mode import server_profile
        visual = not server_profile(state)
        if (visual and confirmed is not None and self.range_blocked(state)
                and self.mouseover_matches(identity, mouse)):
            return [Proposal.make(
                "VISUAL_APPROACH", "Megerősített quest-objektumhoz közelebb lépek használat előtt",
                {"purpose": "INTERACT", "object_use_approach": True,
                 **identity_fields(mouse),
                 "track_id": confirmed.get("track_id"),
                 "visual_signature": confirmed.get("visual_signature"),
                 "expected_tooltips": identity.get("expected_tooltips"),
                 "object_id": identity.get("object_id") or mouse.get("object_id"),
                 "item_id": identity.get("item_id"),
                 "quest_ids": quest_ids, "objective_id": objective.objective_id,
                 "ready_bbox_height": self.object_ready_height(),
                 "range_failures": max(1, int(self.__dict__.get("_range_failure_count") or 0)),
                 "max_seconds": 8.},
                confidence=.85, priority=96,
                evidence=("fresh_quest_object_mouseover", "live_visual_box"))]
        if boxes and visual:
            lock = self.__dict__.get("lock")
            locked = lock.box if lock is not None and lock.active and lock.box is not None else None
            box = next((item for item in boxes if locked is not None
                        and item.get("track_id") == locked.get("track_id")), boxes[0])
            steps.append(Proposal.make(
                "SEEK_VISUAL_CUE", "Látott quest-objektum (gubó): odamegyek és rámutatok",
                {"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
                 "track_id": box.get("track_id"), "visual_signature": box.get("visual_signature"),
                 "query": next(iter(identity.get("expected_tooltips") or ()), "quest object"),
                 "search_area": {"track_id": box.get("track_id")},
                 "quest_id": quest_ids[0], "objective_id": objective.objective_id,
                 "objective_type": getattr(objective, "type", None),
                 **identity, "scan_budget": 2, "time_budget": 15.,
                 "ready_bbox_height": self.object_ready_height()},
                confidence=.8, priority=93 if self.range_blocked(state) else 90,
                evidence=("learned_quest_object_box",)))
        soft = self.soft_target(identity, state)
        # Live 2026-10-19 15:25:10.62: this F7 started the totem's use cast
        # (SPELL_START 22810) beside an attacking Harpy Snatcher, whose spell
        # broke it 0.26 s later.  Combat first; the object waits.
        if soft is not None and not self.range_blocked(state) and not state.get("is_in_combat"):
            steps.append(Proposal.make(
                "OBJECT_USE", "Quest-objektum soft-interact célpontban: ellenőrzött F7 tartalék",
                {"activation_source": "INTERACT_KEY", "binding": "INTERACTTARGET",
                 "object_guid": soft.get("guid"), "object_id": soft.get("object_id"),
                 "object_name": soft.get("name"), "objective_id": objective.objective_id,
                 "quest_ids": quest_ids},
                # Issue #99: an identity-matched soft-interact object is in
                # range now; the visible-box SEEK (90/93) used to starve this
                # verified use.  Quest credit is still verified by the skill.
                confidence=.85, priority=95, evidence=("soft_interact_object",)))
        return steps

    def propose_local_search(self, objective, record, search_area: dict) -> list[Proposal]:
        identity = self.expected_identity(objective)
        query = next(iter(identity.get("expected_tooltips") or ()), None)
        query = str(query or identity.get("object_id") or identity.get("item_id")
                    or getattr(objective, "description", "") or "quest world object")
        return [Proposal.make(
            "SEEK_VISUAL_CUE",
            "Quest-object terület elérve: UNKNOWN cue megközelítése és addon-mouseover azonosítás",
            {"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
             "query": query, "search_area": dict(search_area),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "objective_type": getattr(objective, "type", None),
             **identity, "scan_budget": 4, "time_budget": 22.,
             "ready_bbox_height": .09},
            confidence=max(.6, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=66,
            evidence=("objective_search_area_reached", "object_identity_not_yet_confirmed"))]

