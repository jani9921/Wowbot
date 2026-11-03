"""Walk, ride, or keep the current travel mode for one planner cycle.

User 2026-10-20: "mountolás csak akkor kéne legyen, ha egyáltalán van
mountunk, vagy van mount riding skillünk".  MOUNT is proposed only when

* ``mount_capability_allows`` holds (owned mount + confirmed riding from the
  addon; missing/unknown telemetry fails closed),
* a binding is known: the goal's explicit ``mount_binding``, else an
  action-bar slot holding a mount (``summonmount``, e.g. "Summon Random
  Favorite Mount") with a key bound to it -- dispatch still checks it
  against the bindings cache,
* the client reports that action usable and off cooldown,
* the context allows it (not indoors, swimming, falling, in a vehicle, on a
  taxi, casting or in combat), and
* a long MOVE leads the cycle: no on-foot action is ranked as high.

Hysteresis: after an ordinary dismount the mount is not summoned again for
REMOUNT_SECONDS (the on-foot action it was for runs first). A confirmed
combat dismount may remount for the next long route after combat/loot, and a failed
MOUNT ("can't mount here") is not retried for FAILURE_SECONDS unless the
player moved FAILURE_YARDS away.  Mounted, the route keeps the mount; only
an on-foot skill dismounts. A validated explicit flight path may request a
usable flying mount here; NavigationService owns takeoff/cruise/landing and
ground approach. Being mounted alone continues to mean ground travel.
"""
from __future__ import annotations

from wowbot.query_ports import FlightDeparturePort

import math

from .destination_distance import is_world_yards, world_long_move, world_yards
from .models import Proposal, number
from .mount_capability import mount_capability_allows

WALK, GROUND_MOUNT, KEEP_CURRENT_MODE = "WALK", "GROUND_MOUNT", "KEEP_CURRENT_MODE"
COMBAT_SKILLS = frozenset({"COMBAT", "DEFEND", "ACQUIRE_TARGET", "TARGET"})
HUNT_PURPOSES = frozenset({"APPROACH_SERVER_KILL_TARGET"})
HUNT_MOUNT_YARDS = 120.
ON_FOOT_SKILLS = frozenset({
    "ACQUIRE_TARGET", "COMBAT", "ASSIST", "INTERACT", "TALK", "OBJECT_USE", "LOOT",
    "USE_ON_TARGET", "FOLLOW_INSTRUCTION", "GATHER", "HERB", "MINE", "FISH", "REPAIR",
    "BUY_VENDOR", "OPEN_BAGS", "SELL_VENDOR",
})
REMOUNT_SECONDS = 20.
# User 2026-10-21 ("féluton szállt fel mountra"): live 15:51:10 the agent
# dismounted to loot and at 15:51:17 walked a long turn-in route on foot (the
# remount wait was still running); the MOUNT came only with the next MOVE, a
# minute later.  A running walk is stopped once to mount when this much is
# left and mounting is allowed again.
MID_ROUTE_MOUNT_YARDS = 80.
MID_ROUTE_RETRY_SECONDS = 20.
FAILURE_SECONDS = 20.
FAILURE_YARDS = 30.
# Skyriding travel (user 2026-10-25: "fly from one quest to the next this
# way too"): shorter trips ride or walk; a failed flight walks for a while.
FLY_MIN_YARDS = 250.
CLIMB_FLIGHT_YARDS = 12.      # a target this far above our server height is flown to
# Already on a gliding mount nothing has to be summoned (live 2026-10-25
# 21:23: the Skytop turn-in 180 yd away on the dome walked, found no navmesh
# route and the agent flew off to far quests instead).
FLY_MIN_MOUNTED_YARDS = 60.
FLIGHT_RETRY_SECONDS = 20.


def mount_action(parameters: dict, state: dict) -> dict | None:
    """The action-bar entry the mount key fires, or None when none is known."""
    actions = [entry for entry in state.get("actionbar") or () if isinstance(entry, dict)]
    explicit = parameters.get("mount_binding")
    if explicit:
        return next((entry for entry in actions if entry.get("action") == explicit),
                    {"action": explicit})
    return next((entry for entry in actions
                 if entry.get("kind") == "summonmount" and entry.get("action")
                 and (entry.get("binding_primary") or entry.get("binding_secondary"))), None)


def flight_mount_action(state: dict, mode: str) -> dict | None:
    """Shared capability selection, independent of the task that requested it."""
    actions = [entry for entry in state.get("actionbar") or () if isinstance(entry, dict)
               and entry.get("kind") == "summonmount" and entry.get("action")
               and (entry.get("binding_primary") or entry.get("binding_secondary"))
               and entry.get("is_usable") is True and entry.get("cooldown_remaining", 0) == 0]
    if mode == 'STEADY':
        from .flight_capability import flying_mount_action
        chosen = flying_mount_action(state)
        return chosen if chosen in actions else None
    if mode != "SKYRIDING":
        return None
    specific = next((entry for entry in actions if (entry.get("mount") or {}).get("mount_type_id") in {402, 424}
                     and (entry.get("mount") or {}).get("mount_usable") is True), None)
    if specific is not None:
        return specific
    # This client action explicitly requests the usable favourite mount in
    # the current area. It remains an action ID, resolved by selected cache.
    return next((entry for entry in actions if entry.get("id") == 268435455), None)


def _player_point(state: dict) -> tuple[float, float] | None:
    player = state.get("player_world_position") or {}
    x, y = number(player.get("x")), number(player.get("y"))
    return None if x is None or y is None else (x, y)


class TravelModePolicy:
    """Owns MOUNT/DISMOUNT proposals; the ranker still picks the winner."""

    def __init__(self, *, departure_walk: FlightDeparturePort | None = None) -> None:
        self.departure_walk = departure_walk
        self.mode = WALK
        self.reason = "no_decision"
        self.was_mounted: bool | None = None
        self.was_in_combat = False
        self.combat_dismount = False
        self.dismounted_at: float | None = None
        self.failed_at: float | None = None
        self.failed_point: tuple[float, float] | None = None
        self.noted_action_id = None
        self.mid_route_at: float | None = None
        self.flight_failed_at: float | None = None
        self.noted_flight_action_id = None
        self.flight_mount_wait_until: float | None = None
        self.flight_blockers: list[str] = []
        from wowbot.navigation.mode_transitions import ModeTransitionMachine
        from wowbot.navigation.travel_planner import TravelPlanner
        self.transitions = ModeTransitionMachine()     # spec 30.2: verified mode transitions
        self.planner = TravelPlanner()                 # spec 30.1: candidate trips, explicit legs
        self.travel_plan: dict | None = None

    def snapshot(self) -> dict:
        return {"mode": self.mode, "reason": self.reason,
                "dismounted_at": self.dismounted_at, "mount_failed_at": self.failed_at,
                "flight_blockers": list(self.flight_blockers),
                "flight_mount_wait_until": self.flight_mount_wait_until,
                "transitions": self.transitions.snapshot(),
                "travel_plan": self.travel_plan}

    def observe(self, world, now: float | None) -> None:
        """Read transitions even while an active combat/loot skill owns input."""
        state = world.state
        mounted = state.get("is_mounted")
        combat = state.get("is_in_combat") is True
        if isinstance(mounted, bool):
            if self.was_mounted and not mounted and now is not None:
                self.dismounted_at = now
                self.combat_dismount = combat or self.was_in_combat
            if mounted:
                self.combat_dismount = False
            self.was_mounted = mounted
        self.was_in_combat = combat
        result = (getattr(world, "runtime_context", None) or {}).get("last_result") or {}
        action_id = result.get("action_id")
        from wowbot.navigation.mode_transitions import TransitionKind
        if (result.get("skill") in {"MOUNT", "DISMOUNT"} and action_id is not None and now is not None
                and action_id != self.__dict__.get("transition_action_id")):
            # The key was sent; only the observed mount state verifies it.
            self.transition_action_id = action_id
            self.transitions.begin(TransitionKind(result["skill"]), state, now, action_id=action_id)
        if now is not None:
            self.transitions.observe(state, now)
        if (result.get("skill") == "MOUNT" and action_id is not None
                and action_id != self.noted_action_id):
            self.noted_action_id = action_id
            if result.get("outcome") != "SUCCESS" and now is not None:
                self.failed_at, self.failed_point = now, _player_point(state)
            elif now is not None and result.get('purpose') == 'MOVEMENT_FLIGHT':
                self.flight_mount_wait_until = now+2.
        if (result.get("skill") == "MOVE" and action_id is not None
                and action_id != self.noted_flight_action_id
                and str(result.get("reason") or "").startswith("skyriding_")):
            self.noted_flight_action_id = action_id
            if (result.get("outcome") != "SUCCESS" and now is not None
                    and result.get('reason') != 'skyriding_not_mounted'):
                self.flight_failed_at = now
                self.transitions.fail(TransitionKind.TAKEOFF, state, now, str(result.get("reason")))

    def _blocked(self, state: dict, now: float | None) -> str | None:
        movement = state.get("movement") or {}
        for key, reason in (("is_dead", "dead"), ("is_ghost", "ghost"),
                            ("in_vehicle", "in_vehicle"), ("on_taxi", "on_taxi"),
                            ("is_casting", "casting"), ("is_channeling", "casting"),
                            ("is_in_combat", "in_combat")):
            if state.get(key) is True:
                return reason
        for key in ("indoors", "swimming", "falling"):
            if movement.get(key) is True:
                return key
        if now is None:
            return "no_clock"
        if (state.get('is_mounted') is not True and not self.combat_dismount and self.dismounted_at is not None
                and 0 <= now-self.dismounted_at < REMOUNT_SECONDS):
            return "recently_dismounted"
        if (state.get('is_mounted') is not True and self.failed_at is not None
                and 0 <= now-self.failed_at < FAILURE_SECONDS):
            here = _player_point(state)
            if (self.failed_point is None or here is None
                    or math.dist(here, self.failed_point) < FAILURE_YARDS):
                return "mount_failed_here"
        return None

    def mount_now(self, move: Proposal, goal, world, now: float | None) -> bool:
        """A running walk on foot should stop to mount (see MID_ROUTE_MOUNT_YARDS)."""
        state = world.state
        self.observe(world, now)
        if (move.skill != "MOVE" or now is None or state.get("is_mounted") is True
                or state.get("is_dead") or state.get("is_ghost")
                or (self.mid_route_at is not None and 0 <= now-self.mid_route_at < MID_ROUTE_RETRY_SECONDS)):
            return False
        from .destination_distance import is_world_yards, world_yards
        params = move.parameters
        if params.get('flight_departure') and (state.get('movement') or {}).get('indoors') is False:
            from .flight_capability import flight_blockers, skyriding_blockers
            style = params['flight_departure'].get('flight_style')
            blocked = skyriding_blockers(state) if style == 'SKYRIDING' else flight_blockers(state)
            point = params['flight_departure'].get('point') or {}
            reached = world_yards(state, {**point, 'instance_id': params.get('instance_id')})
            if reached is not None and reached <= 3. and not blocked and self._blocked(state, now) is None:
                self.mid_route_at = now
                return True
        if params.get('flight_departure'):
            return False
        left = world_yards(state, params) if is_world_yards(params) else None
        action = mount_action(goal.parameters, state)
        if (left is None or left <= MID_ROUTE_MOUNT_YARDS or not mount_capability_allows(state)
                or not (action or {}).get("action")
                or not (action.get("is_usable") is True and action.get("cooldown_remaining") == 0)
                or self._blocked(state, now) is not None):
            return False
        self.mid_route_at = now
        return True

    def flight_now(self, move: Proposal, world, now: float | None) -> bool:
        """A running ground MOVE may upgrade after its mount facts settle.

        The medium owner cancels/replans the same task once; this query does
        not create another active skill, issue takeoff input or guess a mount.
        """
        if (world.state.get('is_mounted') is not True
                or move.skill != 'MOVE' or move.parameters.get('flight') is True
                or move.parameters.get('flight_path')):
            return False
        if move.parameters.get('flight_departure'):
            point = move.parameters['flight_departure'].get('point') or {}
            reached = world_yards(world.state, {**point, 'instance_id': move.parameters.get('instance_id')})
            if reached is None or reached > 3.:
                return False
        result = (self._corpse_travel([move], world.state, now)
                  if world.state.get('is_ghost') is True else
                  self._skyriding_travel([move],world.state,now) or self._steady_travel([move],world.state,now))
        return any(p.skill == 'MOVE' and p.parameters.get('flight') is True for p in result or ())

    def _corpse_travel(self, proposals: list[Proposal], state: dict,
                       now: float | None) -> list[Proposal]:
        from .death_recovery_planning import corpse_run_matches
        from .flight_capability import ghost_steady_flight_available
        self.mode, self.reason = WALK, 'corpse_ground_route'
        if now is None or not ghost_steady_flight_available(state):
            return proposals
        result = []
        for proposal in proposals:
            if proposal.skill == 'MOVE' and corpse_run_matches(state, proposal.parameters):
                self.mode, self.reason = 'STEADY', 'corpse_steady_flight'
                result.append(Proposal.make(proposal.skill, proposal.reason,
                    {**proposal.parameters, 'flight': True, 'flight_style': 'STEADY',
                     'require_navmesh': True}, proposal.confidence, proposal.priority,
                    (*proposal.evidence, 'ghost_steady_flight')))
            else:
                result.append(proposal)
        return result

    def _skyriding_travel(self, proposals: list[Proposal], state: dict,
                          now: float | None) -> list[Proposal] | None:
        """Long MOVEs flown by Skyriding, plus a MOUNT on the Skyriding mount
        when on foot.  In the air every MOVE flies (no walking route there).

        The MOVE keeps its destination; ``flight``/``flight_style`` make the
        global planner plan over the terrain and the movement controller fly
        it with SkyridingControl.  None: this cycle travels as before."""
        from wowbot.navigation.flight_path import airborne
        from .destination_distance import is_world_yards, world_yards
        from .flight_capability import skyriding_blockers
        self.flight_blockers = []
        if now is None or state.get('is_dead') is True or state.get('is_ghost') is True:
            return None
        in_air = state.get("is_mounted") is True and airborne(state, now)

        def yards(parameters):
            instance = parameters.get("instance_id", parameters.get("world_map_id"))
            flat = world_yards(state, {**parameters, "instance_id": instance}) or 0.
            # A known height counts (live 17:22: the turn-in 90 yd straight
            # below a ledge was "0 yd" away and never flown to).
            here = state.get("player_world_position") or {}
            z, pz = number(parameters.get("z")), number(here.get("z"))
            if parameters.get("z_known") is True and z is not None and pz is not None and here.get("z_observed") is True:
                return math.hypot(flat, z-pz)
            return flat
        def above(parameters):
            # Live 2026-10-27 17:03: the East Siege Arbalest stood on a bridge
            # 44 yd above us, 1.6 yd away flat; no walking path leads up and
            # 44 yd was below the flight minimum, so the agent walked under
            # it and waited.  A known target this high above us is flown to.
            here = state.get("player_world_position") or {}
            z, pz = number(parameters.get("z")), number(here.get("z"))
            return (parameters.get("z_known") is True and z is not None and pz is not None
                    and here.get("z_observed") is True and abs(z-pz) > CLIMB_FLIGHT_YARDS)
        gliding_mount = state.get("is_mounted") is True and (state.get("flight") or {}).get("can_glide") is True
        minimum = FLY_MIN_MOUNTED_YARDS if gliding_mount else FLY_MIN_YARDS
        moves = [p for p in proposals if p.skill == "MOVE" and not p.parameters.get("flight_path")
                 and is_world_yards(p.parameters)
                 and (in_air or yards(p.parameters) >= minimum or above(p.parameters))]
        if not moves:
            return None
        if not in_air:
            on_foot = [p for p in proposals if p.skill in ON_FOOT_SKILLS]
            lead = max(move.priority for move in moves)
            self.flight_blockers = list(skyriding_blockers(state))
            if (state.get('is_mounted') is True and self.flight_mount_wait_until is not None
                    and now < self.flight_mount_wait_until
                    and (state.get('flight') or {}).get('can_glide') is not True
                    and not any(p.priority >= lead for p in on_foot)):
                self.mode,self.reason = 'WAIT_FLIGHT_READY','mount_flight_telemetry_settling'
                return [p for p in proposals if p not in moves]+[Proposal.make(
                    'WAIT','Repülő mountra felült: friss repülési képességjelzésre vár',
                    {'waiting_for':['MOUNT_FLIGHT_CAPABILITY'],'wait_until':self.flight_mount_wait_until},
                    priority=lead)]
            if (any(p.priority >= lead for p in on_foot) or self._blocked(state, now) is not None
                    or self.flight_blockers
                    or (self.flight_failed_at is not None and 0 <= now-self.flight_failed_at < FLIGHT_RETRY_SECONDS)
                    or (state.get("is_mounted") is not True and not mount_capability_allows(state))):
                return None
        if not in_air:
            lead_move = max(moves, key=lambda move: move.priority)
            decision = self._decide(state, lead_move.parameters, now, flight_style="SKYRIDING",
                                    unreachable="target_height_needs_flight" if above(lead_move.parameters) else None)
            if decision is not None and decision.mode not in {"FLIGHT", "MIXED"}:
                return None
        flights = {id(move): Proposal.make(
            move.skill, move.reason, {**move.parameters, "flight": True, "flight_style": "SKYRIDING", 'travel_mode_policy': 'AUTO'},
            move.confidence, move.priority, (*move.evidence, "skyriding_travel")) for move in moves}
        result = [flights.get(id(proposal), proposal) for proposal in proposals]
        # In the air the existing contract holds: never dismount there.
        self.mode, self.reason = "SKYRIDING", "airborne_no_dismount" if in_air else "long_move_skyriding"
        if state.get("is_mounted") is not True:
            chosen = flight_mount_action(state, "SKYRIDING")
            result.append(Proposal.make(
                "MOUNT", "Mozgás: Skyriding mount a hosszú úthoz",
                {"binding": chosen["action"], "purpose": "MOVEMENT_FLIGHT"},
                priority=max(move.priority for move in moves) + 3,
                evidence=("mount_capability", "skyriding_travel")))
        return result

    @staticmethod
    def _combat_landing(state: dict, fighting: list[Proposal]) -> Proposal | None:
        """In combat in the air: a MOVE to the ground right below (the flight
        loop lands), after which the dismount rule applies."""
        if not state.get("is_in_combat"):
            return None
        position = state.get("player_world_position") or {}
        x, y = position.get("x"), position.get("y")
        if type(x) not in {int, float} or type(y) not in {int, float}:
            return None
        return Proposal.make(
            "MOVE", "Harcban a levegőben: leszállok a földre alattam",
            {"x": float(x), "y": float(y), "coordinate_space": "WORLD_YARDS",
             "instance_id": position.get("instance_id"), "map_id": state.get("map_id"),
             "purpose": "COMBAT_LANDING", "require_navmesh": True, "stop_distance": 6.},
            priority=max((p.priority for p in fighting), default=100.) + 1,
            evidence=("in_combat", "airborne"))

    def _walk_to_open_sky(self, proposals, world, now):
        state = world.state
        if now is None or any(state.get(key) is True for key in (
                'is_in_combat', 'in_vehicle', 'on_taxi', 'is_dead', 'is_ghost', 'loading',
                'is_casting', 'is_channeling')):
            return None
        movement = state.get('movement') or {}
        if movement.get('flying') or movement.get('falling') or movement.get('swimming'):
            return None
        from .destination_distance import is_world_yards
        player = state.get('player_world_position') or {}
        def distant(parameters):
            target_z, own_z = number(parameters.get('z')), number(player.get('z'))
            return ((world_yards(state, parameters) or 0.) >= (
                        FLY_MIN_MOUNTED_YARDS if state.get('is_mounted') is True else FLY_MIN_YARDS)
                    or parameters.get('z_known') is True and player.get('z_observed') is True
                    and target_z is not None and own_z is not None and abs(target_z-own_z) > CLIMB_FLIGHT_YARDS)
        moves = [p for p in proposals if p.skill == 'MOVE' and is_world_yards(p.parameters)
                 and not any(p.parameters.get(key) for key in ('flight_path', 'hover_point', 'flight_departure'))
                 and distant(p.parameters)]
        if not moves:
            return None
        lead = max(moves, key=lambda p: p.priority)
        if any(p.skill in ON_FOOT_SKILLS and p.priority >= lead.priority for p in proposals):
            return None
        from .flight_capability import FLYING_MOUNT_TYPES, SKYRIDING_MOUNT_TYPES
        style = None
        for action in state.get('actionbar') or ():
            mount = action.get('mount') or {} if isinstance(action, dict) else {}
            if (not mount or action.get('kind') != 'summonmount' or not action.get('action')
                    or not (action.get('binding_primary') or action.get('binding_secondary'))
                    or mount.get('mount_collected') is not True):
                continue
            if mount.get('mount_type_id') in SKYRIDING_MOUNT_TYPES and mount.get('mount_steady_flight') is not True:
                style = 'SKYRIDING'
                break
            if (mount.get('mount_type_id') in FLYING_MOUNT_TYPES
                    and (state.get('mount_capability') or {}).get('flying_riding_known') is True):
                style = 'STEADY'
        try:
            departure = self.departure_walk(lead.parameters, state) if style and callable(self.departure_walk) else None
        except Exception:  # unavailable geometry cannot prove a departure leg
            departure = None
        if departure is None:
            return None
        self.mode, self.reason = WALK, 'walk_to_open_sky'
        replacement = Proposal.make(lead.skill, 'Repülés előtt MMAP úton kijutok nyílt ég alá',
            {**lead.parameters, 'flight': False, 'flight_departure': {**departure, 'flight_style': style}},
            lead.confidence, lead.priority, (*lead.evidence, 'verified_takeoff_walk'))
        return [replacement if p is lead else p for p in proposals]

    def _steady_travel(self, proposals, state, now):
        from .flight_capability import can_fly
        from .destination_distance import is_world_yards
        if now is None or not can_fly(state) or self._blocked(state, now) is not None:
            return None
        if self.flight_failed_at is not None and 0 <= now-self.flight_failed_at < FLIGHT_RETRY_SECONDS:
            return None
        mounted = state.get('is_mounted') is True
        minimum = FLY_MIN_MOUNTED_YARDS if mounted else FLY_MIN_YARDS
        player = state.get('player_world_position') or {}
        def other_floor(parameters):
            own, target = number(player.get('z')), number(parameters.get('z'))
            return (player.get('z_observed') is True and parameters.get('z_known') is True
                    and own is not None and target is not None and abs(own-target) > CLIMB_FLIGHT_YARDS)
        moves = [p for p in proposals if p.skill == 'MOVE' and is_world_yards(p.parameters)
                 and not p.parameters.get('flight_path') and (
                     (state.get('movement') or {}).get('flying') is True
                     or (world_yards(state, p.parameters) or 0.) >= minimum or other_floor(p.parameters))]
        if not moves or any(p.skill in ON_FOOT_SKILLS and p.priority >= max(m.priority for m in moves)
                            for p in proposals):
            return None
        if (state.get('movement') or {}).get('flying') is not True:
            lead_move = max(moves, key=lambda move: move.priority)
            decision = self._decide(state, lead_move.parameters, now, flight_style='STEADY',
                                    unreachable='target_height_needs_flight' if other_floor(lead_move.parameters) else None)
            if decision is not None and decision.mode not in {'FLIGHT', 'MIXED'}:
                return None
        result = [Proposal.make(p.skill, p.reason, {**p.parameters, 'flight': True, 'flight_style': 'STEADY', 'travel_mode_policy': 'AUTO'},
                                p.confidence, p.priority, (*p.evidence, 'steady_travel')) if p in moves else p
                  for p in proposals]
        if not mounted:
            action = flight_mount_action(state, 'STEADY')
            if action is None:
                return None
            result.append(Proposal.make('MOUNT', 'Mozgás: Steady repülő mount az úthoz',
                {'binding': action['action'], 'purpose': 'MOVEMENT_FLIGHT'}, priority=max(p.priority for p in moves)+3))
        self.mode, self.reason = 'STEADY', 'long_move_steady'
        return result

    def _decide(self, state: dict, destination: dict, now, *, flight_style, unreachable=None):
        """Spec 30.1: compare the candidate trips; the gates above already
        decided what is possible (capabilities, blockers, hysteresis)."""
        from wowbot.navigation.mode_transitions import TransitionKind
        from wowbot.navigation.travel_planner import TravelOptions
        from wowbot.navigation.flight_path import airborne
        yards = world_yards(state, destination)
        if yards is None or now is None:
            return None
        here = state.get("player_world_position") or {}
        z, pz = number(destination.get("z")), number(here.get("z"))
        if destination.get("z_known") is True and z is not None and pz is not None and here.get("z_observed") is True:
            yards = math.hypot(yards, z-pz)
        options = TravelOptions(
            mounted=state.get("is_mounted") is True, airborne=airborne(state, now),
            mount_blockers=() if mount_capability_allows(state) else ("no_mount_capability",),
            flight_style=flight_style, flight_blockers=(),
            ground_unreachable=unreachable,
            on_foot_after=destination.get("purpose") not in {"ESCORT_FOLLOW", "CORPSE_RUN"},
            mount_failed_recently=self.transitions.recently_failed(TransitionKind.MOUNT, state, now),
            flight_failed_recently=self.transitions.recently_failed(TransitionKind.TAKEOFF, state, now))
        decision = self.planner.plan(yards, options)
        self.travel_plan = {**decision.snapshot(), "at": now}
        return decision

    def apply(self, proposals: list[Proposal], goal, world, now: float | None) -> list[Proposal]:
        state = world.state
        self.observe(world, now)
        if state.get('is_dead') is True or state.get('is_ghost') is True:
            return self._corpse_travel(proposals, state, now)
        explicit = next((proposal for proposal in proposals if proposal.skill == "MOVE"
                         and proposal.parameters.get("flight_path")), None)
        if explicit is not None and state.get("is_mounted") is not True:
            from wowbot.navigation.flight_path import FlightPath, airborne
            path = FlightPath.from_dict(explicit.parameters["flight_path"])
            if not path.air_segment_complete(state) and not airborne(state, now or 0.):
                chosen = flight_mount_action(state, path.mode)
                reason = (self._blocked(state, now) or ("no_mount_capability" if not mount_capability_allows(state) else None)
                          or ("no_usable_flight_mount_binding" if chosen is None else None))
                if reason:
                    self.mode, self.reason = WALK, reason
                    return [proposal for proposal in proposals if proposal is not explicit] + [Proposal.make(
                        "WAIT", "Mozgás: a kért repülési mód előfeltétele hiányzik",
                        {"waiting_for": [reason], "blocked_skill": "MOVE"}, priority=explicit.priority)]
                self.mode, self.reason = GROUND_MOUNT, "mount_for_requested_flight_path"
                return [*proposals, Proposal.make(
                    "MOUNT", "Mozgás: mount a kért repülési útvonalhoz",
                    {"binding": chosen["action"], "purpose": "MOVEMENT_FLIGHT"},
                    priority=explicit.priority + 3, evidence=("mount_capability", "flight_path"))]
        departure = self._walk_to_open_sky(proposals, world, now)
        if departure is not None:
            return departure
        flying = self._skyriding_travel(proposals, state, now) or self._steady_travel(proposals, state, now)
        if flying is not None:
            return flying
        action = mount_action(goal.parameters, state)
        binding = (action or {}).get("action")
        on_foot = [p for p in proposals if p.skill in ON_FOOT_SKILLS]
        if state.get("is_mounted") is True:
            fighting = [p for p in proposals if p.skill in COMBAT_SKILLS]
            if (state.get("movement") or {}).get("flying") is True:
                # Dismounting in the air is a fall.  Attacked in the air (live
                # 2026-10-26, the protodrake quests): land where we are first.
                self.mode, self.reason = KEEP_CURRENT_MODE, "airborne_no_dismount"
                landing = self._combat_landing(state, fighting)
                return [*proposals, landing] if landing is not None else proposals
            if binding and state.get("is_in_combat") and not state.get("is_casting"):
                # Live 2026-10-26 14:14: attacked on the mount, DEFEND kept
                # failing OUT_OF_RANGE and the agent stood still.  On the
                # mount (and on the Skyriding bar) there is nothing to fight
                # with: get off first.  A mount on a multi-action bar keeps
                # its key on the Skyriding bar.
                lead = max(fighting, key=lambda p: p.priority) if fighting else None
                self.mode, self.reason = WALK, "dismount_for_combat"
                return [*proposals, Proposal.make(
                    "DISMOUNT", "Harcban mounton: leszállok, hogy harcolni tudjak",
                    {"binding": binding, "for_skill": lead.skill if lead else "DEFEND",
                     "purpose": "COMBAT_DISMOUNT"},
                    priority=(lead.priority if lead else 100.) + 1)]
            if binding and on_foot and not state.get("is_casting") and not state.get("is_in_combat"):
                lead = max(on_foot, key=lambda p: p.priority)
                self.mode, self.reason = WALK, f"dismount_for_{lead.skill}"
                return [*proposals, Proposal.make(
                    "DISMOUNT", "Megerősített, gyalogos interakció előtt a kijelölt mount-binding kikapcsolása",
                    {"binding": binding, "for_skill": lead.skill}, priority=lead.priority+1)]
            self.mode, self.reason = KEEP_CURRENT_MODE, "mounted"
            return proposals
        self.mode = WALK
        long_move = next((p for p in proposals
                          if p.skill == "MOVE" and world_long_move(world, p.parameters)), None)
        if long_move is None:
            self.reason = "no_long_move"
        elif not mount_capability_allows(state):
            self.reason = "no_mount_capability"
        elif not binding:
            self.reason = "no_mount_binding"
        elif not (action.get("is_usable") is True and action.get("cooldown_remaining") == 0):
            self.reason = "mount_action_unusable"
        elif any(p.priority >= long_move.priority for p in on_foot):
            self.reason = "on_foot_action_leads"
        elif (long_move.parameters.get("purpose") in HUNT_PURPOSES
              and (yards := world_yards(state, long_move.parameters)) is not None and yards < HUNT_MOUNT_YARDS):
            # Live 2026-10-26 14:13-14:23: a mount (1.5 s cast) before every
            # 40-60 yd hop between quest mobs, then off again for the fight.
            self.reason = "hunting_nearby"
        else:
            self.reason = self._blocked(state, now) or ""
        if not self.reason and is_world_yards(long_move.parameters):
            decision = self._decide(state, long_move.parameters, now, flight_style=None)
            if decision is not None and decision.mode != "MOUNTED_GROUND":
                self.reason = "travel_planner_prefers_" + str(decision.mode).lower()
        if self.reason:
            return proposals
        self.mode, self.reason = GROUND_MOUNT, "long_move"
        return [*proposals, Proposal.make(
            "MOUNT", "Hosszabb út, megerősített mount + riding képességgel",
            {"binding": binding}, priority=long_move.priority+3,
            evidence=("mount_capability", "long_move"))]
