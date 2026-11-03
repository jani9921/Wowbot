"""Fight from a quest vehicle by server positions (server mode).

Live 2026-10-23 01:32-01:33 (Training Wings 70061, the flying Ruby Whelpling,
button 1 "Burning Bark", 20 yd): the screen-driven vehicle attack is off in
server mode, so only a navmesh MOVE was left -- a flying vehicle has no
walking route ("required_navmesh_route_unavailable") -- and COMBAT/DEFEND
reported unsupported_mechanic while the weedlings came with exact server
positions.  Here the same server facts as on foot drive the vehicle:

* a selected live objective unit with the attack button in range and in
  front: press the button (the existing VEHICLE_ABILITY skill);
* selected but out of range or facing away: fly/drive toward its server
  point and face it (a flying vehicle flies straight, no navmesh);
* nothing selected: Tab with a GUID check when the nearest objective unit is
  straight ahead within Tab range, otherwise approach it first.

Nothing here is keyed to one vehicle, spell or quest.
"""
from __future__ import annotations

import math

from .hover_control import pitch_steerable, vehicle_sample
from .models import Proposal, number
from .packet_entity_facts import (TAB_SERVER_GUID, TAB_TARGET_YARDS, kill_objective_entries,
                                  kill_objective_units, tab_target_check)

FACING_RADIANS = .6
CLOSE_RANGE_YARDS = 5.          # an ability without a reported range: close in
RANGE_USE_FRACTION = .6         # stop well inside the button's range
TAB_PRESS_SECONDS = 2.
DESCEND_SECONDS = 2.5           # one bounded descent step at a time ...
DESCEND_LIMIT = 6               # ... and no endless sinking per target
# A flying vehicle hovers above and short of its target (live 2026-10-26:
# the whelp at z 284, weedlings at z 161-278): inside a 20 yd button and the
# Tab range, facing it on arrival.
HOVER_ABOVE_YARDS = 6.
HOVER_BACK_YARDS = 6.
HOVER_STOP_YARDS = 3.
# A forward-dash button on scene ClientActors (Giant Boar, Trample: a ~30 yd
# lunge along the facing, damage within 8 yd for 2 s; walking into a large
# one without it knocks the boar back).
DASH_START_YARDS = 12.
DASH_RANGE_YARDS = 18.
DASH_FACING_RADIANS = .2
DASH_CREDIT_SECONDS = 6.
DASH_MISSES = 2
# Live 2026-10-26 11:31:49: the first plan, 0.6 s after boarding and before
# the vehicle's first own packet, drove the flying whelp as a ground vehicle
# for 33 s.  Wait this long for the vehicle's packets.
BOARDING_EVIDENCE_SECONDS = 3.
AIM_PITCH_RADIANS = .15
# The same approach proposed while already at its hover point: the arrival
# did not make the unit selectable; skip that unit for a while.
REARRIVE_LIMIT = 3
REARRIVE_SKIP_SECONDS = 30.


def flying(state: dict) -> bool:
    """In the air, or in a vehicle that can fly (live 2026-10-26 11:31: the
    addon's flying flag flickered after boarding and the whelp touched down
    on the Lifeshrine; its own packets kept CAN_FLY)."""
    if (state.get("movement") or {}).get("flying") is True:
        return True
    sample = vehicle_sample(state)
    return state.get("in_vehicle") is True and bool(sample.get("flying") or sample.get("can_fly"))


def _height(state: dict) -> float | None:
    """The vehicle's own measured height (its client movement packets)."""
    z = number((vehicle_sample(state).get("position") or {}).get("z"))
    if z is not None:
        return z
    position = state.get("player_world_position") or {}
    return number(position.get("z")) if position.get("z_observed") is True else None


def _facing(state: dict) -> float | None:
    return number(vehicle_sample(state).get("facing", state.get("orientation")))


def _bearing_error(state: dict, point: dict) -> float | None:
    position = state.get("player_world_position") or {}
    px, py, facing = number(position.get("x")), number(position.get("y")), _facing(state)
    if None in (px, py, facing):
        return None
    bearing = math.atan2(point["y"]-py, point["x"]-px)
    return abs((bearing-facing+math.pi) % math.tau - math.pi)


def _pitch_error(state: dict, point: dict) -> float | None:
    """|aim pitch at the point - the vehicle's pitch|, or None when unknown."""
    sample = vehicle_sample(state)
    pitch, where = number(sample.get("pitch")), sample.get("position") or {}
    x, y, z = number(where.get("x")), number(where.get("y")), number(where.get("z"))
    if None in (pitch, x, y, z) or number(point.get("z")) is None:
        return None
    wanted = math.atan2(point["z"]-z, max(1., math.hypot(point["x"]-x, point["y"]-y)))
    return abs((wanted-pitch+math.pi) % math.tau - math.pi)


def _distance(state: dict, point: dict) -> float | None:
    """3D when both heights are known (a flying vehicle), else flat."""
    position = state.get("player_world_position") or {}
    px, py = number(position.get("x")), number(position.get("y"))
    if px is None or py is None:
        return None
    flat = math.hypot(point["x"]-px, point["y"]-py)
    z, pz = number(point.get("z")), _height(state)
    return math.hypot(flat, z-pz) if flying(state) and z is not None and pz is not None else flat


class ServerVehicleCombatPolicy:
    def __init__(self) -> None:
        self.tab_pressed: dict[str, float] = {}
        self.descended: dict[str, list[float]] = {}
        self.scene_done: set[str] = set()
        self.scene_misses: dict[str, int] = {}
        self.scene_dash: tuple[str, float] | None = None
        self.scene_progress: dict[str, float] = {}
        self.boarded: tuple[str, float] | None = None
        self.rearrived: dict[str, int] = {}
        self.skip_until: dict[str, float] = {}
        self.range_trusted: set[tuple[str, str]] = set()

    def propose(self, state: dict, action: dict, *, cooling: bool, mode: str | None = None) -> list[Proposal]:
        """Proposals for the vehicle's attack ``action`` (from vehicle_abilities)."""
        now = number(state.get("monotonic_time"))
        if now is None or state.get("in_vehicle") is not True:
            self.boarded = None
            return []
        vehicle = str(state.get("vehicle_guid") or "vehicle")
        if self.boarded is None or self.boarded[0] != vehicle:
            self.boarded = (vehicle, now)
        if (not vehicle_sample(state) and (state.get("movement") or {}).get("flying") is not True
                and now-self.boarded[1] < BOARDING_EVIDENCE_SECONDS):
            return [Proposal.make("WAIT", "Járműbe szálltam: várom a jármű első saját mozgás-csomagját (repül-e)",
                                  {"waiting_for": ["VEHICLE_MOVER_PACKET"], "purpose": "VEHICLE_BOARDING"},
                                  priority=104)]
        units = {str(unit["guid"]): unit for unit in kill_objective_units(state)
                 if now >= self.skip_until.get(str(unit["guid"]), -math.inf)}
        target = state.get("target") or {}
        attacker = self._attacker(state, target)
        if attacker is not None and str(attacker["guid"]) not in units:
            # In combat any selected live enemy is fought with the vehicle's
            # button; COMBAT/DEFEND cannot act from a vehicle.
            units[str(attacker["guid"])] = attacker
        if not units:
            return self._scene_actors(state, action, cooling, mode)
        # Range/usability are live per sample: read the button as it is now.
        action = next((item for item in state.get("actionbar") or ()
                       if isinstance(item, dict) and item.get("action") == action.get("action")
                       and item.get("source") == "VEHICLE_BAR"), action)
        reach = number(action.get("max_range")) or 0.
        reach = reach if reach > 0. else CLOSE_RANGE_YARDS
        selected = units.get(str(target.get("guid") or ""))
        if selected is not None and target.get("dead", target.get("is_dead")) is not True:
            return self._engage(state, action, selected, reach, cooling, mode=mode)
        ranked = sorted(((distance, unit) for unit in units.values()
                         if (distance := _distance(state, unit)) is not None),
                        key=lambda row: (row[0], str(row[1]["guid"])))
        if not ranked:
            return []
        distance, unit = ranked[0]
        ready, _reason = tab_target_check(state, unit["guid"], airborne=flying(state))
        last = self.tab_pressed.get(str(unit["guid"]))
        if ready and (last is None or now-last >= TAB_PRESS_SECONDS):
            self.tab_pressed[str(unit["guid"])] = now
            return [Proposal.make(
                "TARGET", "Járműből: a szerver szerint előttem a legközelebbi quest-mob, Tab GUID-ellenőrzéssel",
                {"guid": unit["guid"], "activation_source": TAB_SERVER_GUID, "npc_id": unit.get("entry_id"),
                 "acceptable_guids": sorted(units)[:12], "quest_ids": [unit["quest_id"]],
                 "objective_id": unit["objective_id"], "purpose": "VEHICLE_TARGET"},
                confidence=.85, priority=104, evidence=("server_unit_position", "in_vehicle"))]
        stop = min(TAB_TARGET_YARDS*.6, reach*RANGE_USE_FRACTION) if distance > TAB_TARGET_YARDS*.6 else max(1., distance)
        move = self._approach(state, unit, stop, "Járművel a legközelebbi quest-mob felé (szerver-pozíció)")
        hover = move.parameters.get("hover_point")
        position = state.get("player_world_position") or {}
        if hover and math.hypot(hover["x"]-(number(position.get("x")) or math.inf),
                                hover["y"]-(number(position.get("y")) or math.inf)) <= HOVER_STOP_YARDS:
            # Already there and still not selectable (live 11:32:51-11:33:46:
            # ~100 instant re-arrivals): give the unit up for a while.
            count = self.rearrived[str(unit["guid"])] = self.rearrived.get(str(unit["guid"]), 0) + 1
            if count >= REARRIVE_LIMIT:
                self.rearrived.pop(str(unit["guid"]), None)
                self.skip_until[str(unit["guid"])] = now + REARRIVE_SKIP_SECONDS
        return [move]

    @staticmethod
    def _aim(state: dict, unit: dict) -> Proposal:
        position = state.get("player_world_position") or {}
        where = vehicle_sample(state).get("position") or position
        return Proposal.make(
            "MOVE", "Járművel a quest-mobra célzok: felé fordulok és a pitch-et rá állítom (a lövedék arra repül)",
            {"x": where["x"], "y": where["y"], "z": where["z"], "z_known": True,
             "z_source": "PACKET_VEHICLE_POSE", "face_on_arrival": True,
             "hover_point": {k: where[k] for k in ("x", "y", "z")},
             "face_towards": {k: unit[k] for k in ("x", "y", "z")}, "aim_pitch": True,
             "coordinate_space": "WORLD_YARDS", "instance_id": position.get("instance_id"),
             "map_id": state.get("map_id"), "purpose": "VEHICLE_AIM", "direct_flight": True,
             "require_navmesh": False, "stop_distance": HOVER_STOP_YARDS,
             "server_entity_guid": unit["guid"], "quest_id": unit["quest_id"], "objective_id": unit["objective_id"]},
            confidence=.85, priority=104, evidence=("server_unit_position", "vehicle_pitch_packets"))

    def _engage(self, state: dict, action: dict, unit: dict, reach: float, cooling: bool,
                *, mode: str | None = None) -> list[Proposal]:
        distance = _distance(state, unit)
        error = _bearing_error(state, unit)
        in_range = action.get("in_range")
        # Live 2026-10-26: the whelp's bar reported in_range False for both
        # buttons always -- at 6 yd too, and on the cast that credited.  A
        # False counts only once this vehicle's button has also said True.
        key = (str(state.get("vehicle_guid") or "vehicle"), str(action.get("action")))
        if in_range is True:
            self.range_trusted.add(key)
        elif in_range is False and key not in self.range_trusted:
            in_range = None
        close_enough = (in_range is True or (in_range is None and distance is not None
                                             and distance <= reach))
        if close_enough and (error is None or error <= FACING_RADIANS):
            if cooling:
                return [Proposal.make("WAIT", f"Jármű-képességre vár: {action.get('name') or action.get('action')} (újratöltés / használhatóság)",
                                      {"waiting_for": ["VEHICLE_ABILITY_READY"], "purpose": "VEHICLE_ATTACK",
                                       "guid": unit["guid"], "spell_id": action.get("id"),
                                       "binding": action["action"], "cooldown_remaining": action.get("cooldown_remaining")},
                                      priority=104)]
            from .vehicle_abilities import db2_trajectory
            aim = _pitch_error(state, unit) if flying(state) and pitch_steerable(state) else None
            if aim is not None and aim > AIM_PITCH_RADIANS and db2_trajectory([action.get("id")]):
                # The missile flies along the vehicle's pitch: aim it first
                # (hover in place, facing and pitched at the unit).
                return [self._aim(state, unit)]
            return [Proposal.make(
                "VEHICLE_ABILITY", "Járműből a kijelölt quest-mobra: a jármű képessége hatótávon belül",
                {"guid": unit["guid"], "aim_guid": unit["guid"], "binding": action["action"],
                 "spell_id": action.get("id"), "ability_name": action.get("name"), "use_mode": mode or "TARGETED",
                 "quest_ids": [unit["quest_id"]] if unit["quest_id"] else [],
                 "objective_ids": [unit["objective_id"]] if unit["objective_id"] else [],
                 "purpose": "VEHICLE_ATTACK"},
                confidence=.9, priority=105, evidence=("server_unit_position", "vehicle_button_in_range"))]
        stop = reach*RANGE_USE_FRACTION if not close_enough else max(1., distance or 1.)
        now = number(state.get("monotonic_time"))
        steps = self.descended.setdefault(str(unit["guid"]), [])
        if (flying(state) and _height(state) is None and in_range is False and distance is not None and now is not None
                and distance <= stop + 2. and len(steps) < DESCEND_LIMIT
                and (not steps or now-steps[-1] >= DESCEND_SECONDS)):
            # Above it within range on the map, yet the client says out of
            # range: the vehicle flies too high.  One bounded step down.
            steps.append(now)
            return [Proposal.make(
                "RECOVER", "Járművel a quest-mob fölött, de hatótávon kívül: lejjebb ereszkedek",
                {"recovery_step": "DESCEND", "purpose": "VEHICLE_DESCEND", "attempt": len(steps),
                 "server_entity_guid": unit["guid"]},
                confidence=.8, priority=104, evidence=("server_unit_position", "vehicle_button_out_of_range"))]
        return [self._approach(state, unit, stop, "Járművel a kijelölt quest-mob felé: hatótávra és szembe")]

    def _scene_actors(self, state: dict, action: dict, cooling: bool, mode: str | None) -> list[Proposal]:
        """Objective units that are scene ClientActors (no server unit): their
        DB2 spawn points (2026-10-26, Giant Boar).  A ClientActor cannot be
        selected, so only an untargeted button hits it: a forward dash is
        lined up from DASH_START_YARDS short and fired through it, an
        around-you/cone button is fired next to it, facing it."""
        from .vehicle_abilities import CLOSE, FORWARD_DASH
        scene = state.get("packet_scene") or {}
        now = number(state.get("monotonic_time"))
        if (mode not in {FORWARD_DASH, CLOSE} or flying(state) or scene.get("active") is not True
                or type(scene.get("package_id")) is not int or now is None):
            return []
        dash = mode == FORWARD_DASH
        catalog = self.__dict__.get("_catalog")
        if catalog is None:
            from wowbot.quests.client_catalog import ClientCatalog
            catalog = self._catalog = ClientCatalog()
        spawns = catalog.scene_actor_spawns(scene["package_id"])
        wanted = kill_objective_entries(state)
        targets = []
        for creature, points in spawns.items():
            if str(creature) not in wanted:
                continue
            quest_id, objective_id = wanted[str(creature)]
            for index, point in enumerate(points):
                targets.append({**point, "id": "%s:%s" % (point["path_id"], index), "entry_id": creature,
                                "quest_id": quest_id, "objective_id": objective_id})
        if not targets:
            return []
        self._note_scene_progress(state, targets, now)
        ranked = sorted(((distance, target["id"], target) for target in targets
                         if target["id"] not in self.scene_done
                         and (distance := _distance(state, target)) is not None), key=lambda row: row[:2])
        if not ranked:
            return []
        distance, _id, target = ranked[0]
        error = _bearing_error(state, target)
        reach, aim = (DASH_RANGE_YARDS, DASH_FACING_RADIANS) if dash else (CLOSE_RANGE_YARDS, FACING_RADIANS)
        if distance <= reach and error is not None and error <= aim:
            if cooling:
                return [Proposal.make("WAIT", "Jármű-képesség: roham folyamatban / újratöltés",
                                      {"waiting_for": ["VEHICLE_ABILITY_READY"]}, priority=104)]
            self.scene_dash = (target["id"], now)
            return [Proposal.make(
                "VEHICLE_ABILITY", "Járművel a scene-célpontra fordulva: előre-roham rajta keresztül" if dash
                else "Járművel a scene-célpont mellett, felé fordulva: a jármű képessége",
                {"guid": None, "aim_guid": None, "binding": action["action"], "spell_id": action.get("id"),
                 "ability_name": action.get("name"), "use_mode": mode,
                 "quest_ids": [target["quest_id"]], "objective_ids": [target["objective_id"]],
                 "purpose": "VEHICLE_SCENE_ACTOR_DASH" if dash else "VEHICLE_SCENE_ACTOR_ATTACK",
                 "scene_actor": target["id"]},
                confidence=.85, priority=105, evidence=("server_scene", "client_db2_scene_actor"))]
        position = state.get("player_world_position") or {}
        px, py = number(position.get("x")), number(position.get("y"))
        flat = math.hypot(target["x"]-px, target["y"]-py)
        back = min(DASH_START_YARDS, max(0., flat-1.)) if dash else 0.
        ux, uy = ((target["x"]-px)/flat, (target["y"]-py)/flat) if flat > 1e-3 else (0., 0.)
        start = {"x": target["x"] - ux*back, "y": target["y"] - uy*back}
        return [Proposal.make(
            "MOVE", "Járművel a scene-célpont elé, felé fordulva (DB2 spawn-pont)",
            {**start, "coordinate_space": "WORLD_YARDS", "instance_id": position.get("instance_id"),
             "map_id": state.get("map_id"), "purpose": "VEHICLE_ATTACK_APPROACH", "require_navmesh": True,
             "stop_distance": 3., "face_on_arrival": True,
             "face_towards": {"x": target["x"], "y": target["y"], "instance_id": position.get("instance_id")},
             "quest_id": target["quest_id"], "objective_id": target["objective_id"], "scene_actor": target["id"]},
            confidence=.8, priority=103, evidence=("server_scene", "client_db2_scene_actor"))]

    def _note_scene_progress(self, state: dict, targets: list[dict], now: float) -> None:
        """A credit after a dash crosses that target off; a dash without one,
        twice, gives it up (it may already have been trampled before)."""
        quests = {t["quest_id"] for t in targets}
        for quest in state.get("active_quests") or ():
            qid = str((quest or {}).get("quest_id"))
            if qid not in quests:
                continue
            total = sum(number(row.get("current")) or 0. for row in quest.get("objectives") or ()
                        if isinstance(row, dict))
            previous = self.scene_progress.get(qid)
            self.scene_progress[qid] = total
            if previous is not None and total > previous:
                if self.scene_dash is not None and now-self.scene_dash[1] <= DASH_CREDIT_SECONDS:
                    self.scene_done.add(self.scene_dash[0])
                    self.scene_dash = None
                else:
                    nearest = min(targets, key=lambda t: _distance(state, t) or math.inf)
                    self.scene_done.add(nearest["id"])
        if self.scene_dash is not None and now-self.scene_dash[1] > DASH_CREDIT_SECONDS:
            target_id = self.scene_dash[0]
            self.scene_misses[target_id] = self.scene_misses.get(target_id, 0) + 1
            if self.scene_misses[target_id] >= DASH_MISSES:
                self.scene_done.add(target_id)
            self.scene_dash = None

    @staticmethod
    def _attacker(state: dict, target: dict) -> dict | None:
        """The selected live enemy while in combat, at its server point."""
        from .packet_entity_facts import best_position
        guid = str(target.get("guid") or "")
        if (not guid or not state.get("is_in_combat")
                or target.get("attackable", target.get("is_attackable")) is not True
                or target.get("dead", target.get("is_dead")) is True):
            return None
        value = (state.get("packet_entities") or {}).get(guid) or {}
        point = best_position(value) if value and not value.get("removed") else None
        if point is None:
            where = target.get("world_position") or {}
            if number(where.get("x")) is None or number(where.get("y")) is None:
                return None
            point = {"x": float(where["x"]), "y": float(where["y"]), "z": number(where.get("z")) or 0.}
        return {**point, "guid": guid, "entry_id": target.get("npc_id"), "quest_id": "", "objective_id": ""}

    @staticmethod
    def _hover_point(state: dict, unit: dict) -> dict | None:
        position = state.get("player_world_position") or {}
        px, py, z = number(position.get("x")), number(position.get("y")), number(unit.get("z"))
        if px is None or py is None or z is None:
            return None
        flat = math.hypot(unit["x"]-px, unit["y"]-py)
        back = min(HOVER_BACK_YARDS, flat)
        ux, uy = ((unit["x"]-px)/flat, (unit["y"]-py)/flat) if flat > 1e-3 else (0., 0.)
        return {"x": unit["x"] - ux*back, "y": unit["y"] - uy*back, "z": z + HOVER_ABOVE_YARDS}

    @staticmethod
    def _approach(state: dict, unit: dict, stop: float, reason: str) -> Proposal:
        position = state.get("player_world_position") or {}
        airborne = flying(state)
        hover = ServerVehicleCombatPolicy._hover_point(state, unit) if airborne else None
        if hover is not None:
            stop = HOVER_STOP_YARDS
        return Proposal.make(
            "MOVE", reason,
            {"x": hover["x"] if hover else unit["x"], "y": hover["y"] if hover else unit["y"],
             # Arrive facing it (and pitched at it where the pitch steers):
             # Tab needs it in front.
             **({"hover_point": hover, "z": hover["z"], "z_known": True,
                 "z_estimated": True, "z_source": "VEHICLE_HOVER_POINT", "aim_pitch": True,
                 "face_towards": {k: unit[k] for k in ("x", "y", "z")}} if hover else {}),
             **({"z": unit["z"], "z_known": True, "z_source": "PACKET_ENTITY"} if not airborne else {}),
             "coordinate_space": "WORLD_YARDS", "instance_id": position.get("instance_id"),
             "map_id": state.get("map_id"), "purpose": "VEHICLE_ATTACK_APPROACH",
             # A flying vehicle flies straight; walking routes do not apply.
             "direct_flight": airborne, "require_navmesh": not airborne,
             "stop_distance": round(stop, 1), "face_on_arrival": True,
             "server_entity_guid": unit["guid"], "quest_id": unit["quest_id"],
             "objective_id": unit["objective_id"]},
            confidence=.85, priority=103, evidence=("server_unit_position", "in_vehicle"))
