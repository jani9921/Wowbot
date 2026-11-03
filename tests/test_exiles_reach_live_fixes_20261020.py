"""Generic regressions derived from the 17:25-18:51 Exile's Reach recording.

Only RecordingExecutor / pure FSMs / mocked navigation are used; no live
client input, capture dependency or user's persistent database is opened.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.combat_planning import CombatPlanningPolicy
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.navigation_situation import NavigationSituationPolicy
from wowbot.agent.planner import Planner
from wowbot.agent.planning_orchestration import PlanningOrchestrator
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.recovery_planning import RecoveryPlanner
from wowbot.agent.server_loot_planning import ServerLootPolicy
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.runtime import FailureReason, SkillStatus
from wowbot.runtime.supervisor import Supervisor, SupervisorDirectiveKind
from wowbot.skills import CombatSkill
from wowbot.verification.quest_dialog import QuestDialogVerifier

from test_agent_core import agent, state
from test_m0_combat_loot_skills import active, combat_state
from test_combat_server_facing_20261020 import MURLOC, world as facing_world
from test_npc_turnin_feedback_20261018 import cue_scene, route
from test_server_kill_target_20261020 import SNATCHER, unit, state as server_state


@pytest.mark.parametrize("target", [None, {"guid": "npc", "attackable": False},
                                   {"guid": "corpse", "attackable": True, "dead": True}])
def test_in_combat_never_falls_through_to_quest_move_map_or_dialog(target):
    world = WorldModel()
    world.ingest(Observation.create(state(10., is_in_combat=True, target=target,
        quest_ui={"open": True, "action": "ACCEPT", "quest_id": 42, "x": .4, "y": .8}), 10.))
    planner = Planner(SkillRegistry())
    # No quest policy, map search or dialog planning should run at this boundary.
    planner.quest.propose = lambda *a, **k: pytest.fail("quest planning during survival combat")
    proposals = planner.candidates(Goal.parse("Questelj", 1.), world, 10.)
    assert proposals and all(Supervisor.combat_admissible(p.skill, p.parameters) for p in proposals)
    assert not any(p.skill in {"MOVE", "OPEN_MAP", "QUEST_DIALOG", "LOOT"} for p in proposals)


def test_combat_wait_is_not_immediately_cancelled_as_another_combat_start():
    s = {"is_in_combat": True}
    running = active("WAIT", {"waiting_for": ["COMBAT_TARGET_EVIDENCE"]}, s)
    sup = Supervisor()
    for t in (1., 1.1, 1.2):
        directive = sup.evaluate(s, running, t)
        assert directive.kind is SupervisorDirectiveKind.CONTINUE
        assert directive.event is None and not directive.cancel_active
    move = active("MOVE", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION"}, s)
    assert sup.evaluate(s, move, 2.).suspend_active


def test_recording_agent_defends_instead_of_starting_and_cancelling_quest_moves():
    bot, executor = agent()
    payload = combat_state()
    for t in (1., 1.2, 1.4, 1.6):
        bot.tick(state(t, **payload, is_in_combat=True), t)
    assert any(c.binding == "ACTIONBUTTON1" for c in executor.commands)
    assert not any(c.binding in {"MOVEFORWARD", "TOGGLEWORLDMAP"} for c in executor.commands)


def test_facing_probe_uses_harmful_binding_not_another_objects_f7():
    skill = CombatSkill(SimpleNamespace(contains=lambda binding: True))
    first = facing_world((3., 0.))
    first.update(monotonic_time=1., target_sample_time=1., soft_targets_sample_time=1.,
                 soft_targets=[{"source_unit": "softinteract", "guid": "GameObject-catapult"}])
    running = active("COMBAT", {"guid": MURLOC}, first)
    skill.begin(running, first, 1.)
    wrong = facing_world((3., -2.5), ui_error="You are facing the wrong way.", sequence=1)
    wrong.update(monotonic_time=2., target_sample_time=2., soft_targets_sample_time=2.,
                 soft_targets=first["soft_targets"])
    turned = skill.verify(running, wrong, 2.)
    assert turned.status is SkillStatus.RUNNING
    assert [c.binding for c in turned.commands] == ["TURNRIGHT", "ACTIONBUTTON1"]


@pytest.mark.parametrize("soft", ["GameObject-catapult", "another-mob"])
def test_autoattack_falls_back_to_confirmed_hover_without_wrong_f7(soft):
    skill = CombatSkill(SimpleNamespace(contains=lambda binding: binding != "STARTATTACK"))
    initial = combat_state()
    initial["actionbar"][0]["is_usable"] = False
    initial["target"]["distance"] = 3.
    initial["target"]["screen_position"] = {"x": .52, "y": .48, "sample_time": 1.}
    initial.update(monotonic_time=1., target_sample_time=1., soft_targets_sample_time=1.,
                   soft_targets=[{"source_unit": "softinteract", "guid": soft}])
    running = active("COMBAT", {"guid": "mob-1"}, initial)
    started = skill.begin(running, initial, 1.)
    assert started.status is SkillStatus.RUNNING
    assert [c.kind for c in started.commands] == ["HOVER"]
    assert running.skill_context["combat"]["auto_attack_dispatches"] == 0
    # A bound Start Attack key (2026-10-21) attacks the selection, no F7, no hover.
    bound = CombatSkill(SimpleNamespace(contains=lambda binding: True))
    started = bound.begin(active("COMBAT", {"guid": "mob-1"}, initial), initial, 1.)
    assert [c.binding for c in started.commands] == ["STARTATTACK"]


def test_matching_interact_recipient_keeps_existing_melee_fallback():
    skill = CombatSkill(SimpleNamespace(contains=lambda binding: True))
    initial = combat_state()
    initial["actionbar"][0]["is_usable"] = False
    initial["target"]["distance"] = 3.
    initial.update(monotonic_time=1., target_sample_time=1., soft_targets_sample_time=1.,
                   soft_targets=[{"source_unit": "softinteract", "guid": "mob-1"}])
    started = skill.begin(active("COMBAT", {"guid": "mob-1"}, initial), initial, 1.)
    assert [c.binding for c in started.commands] == ["INTERACTTARGET"]


def corpse_state(distance=44.64, *, flags=4, owned=True, z=50.):
    value = server_state(unit(SNATCHER, distance, 0., z=z, flags=flags))
    value.update(session_id="exile-test", frame_id="f100", timestamp=100.,
                 player_present=True, target=None,
                 confirmed_corpse_anchors=[{"guid": SNATCHER, "ownership_confirmed": owned,
                     "source": "ADDON_CORPSE_TOOLTIP_EVENT", "x": .1226, "y": .6535}],
                 owned_corpse_guids=[SNATCHER] if owned else [])
    return value


def test_own_corpse_outside_40_yards_is_approached_not_hovered_at_old_point():
    live = corpse_state()
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    world.state.update(deepcopy(live))  # inject the recorded canonical anchor projection
    old = CombatPlanningPolicy(SkillRegistry()).propose(world, Goal.parse("Questelj", 1.), 100., QuestDomain())
    assert not any(p.skill == "LOOT" and p.parameters.get("guid") == SNATCHER for p in old.proposals)
    move, = ServerLootPolicy().propose(live)
    assert move.skill == "MOVE" and move.parameters["purpose"] == "APPROACH_SERVER_CORPSE"
    assert move.parameters["x"] == 44.64 and move.parameters["require_navmesh"]
    assert PlanningOrchestrator._local_interaction_pending([move])


def test_unconfirmed_far_corpse_does_not_extend_the_normal_search_radius():
    assert ServerLootPolicy().propose(corpse_state(owned=False)) == []


@pytest.mark.parametrize("distance,z,flags", [(2., 50., 0), (2., 70., 4), (120., 50., 4)])
def test_ineligible_other_floor_or_unbounded_corpses_are_not_clicked(distance, z, flags):
    live = corpse_state(distance, z=z, flags=flags)
    assert ServerLootPolicy().propose(live) == []
    if flags == 0:
        assert CombatPlanningPolicy._reported_empty(live, SNATCHER)
    else:
        assert CombatPlanningPolicy._corpse_needs_world_approach(live, SNATCHER)


def test_server_turnin_route_does_not_stop_for_an_unidentified_far_marker():
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    move = route(knowledge_priority="SERVER_LIVE", guid="giver", npc_ids=[123], x=500.)
    seen = cue_scene()
    assert movement_visual_interrupt(SimpleNamespace(proposal=move), seen.state) is None


def test_known_server_ender_route_ignores_visual_box_renumbering():
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    move = route(knowledge_priority="SERVER_LIVE", guid="giver", npc_ids=[123])
    attempt = SimpleNamespace(proposal=move)
    for track in ("old-id", "new-id", "another-id"):
        assert movement_visual_interrupt(attempt, cue_scene(11., track=track).state) is None


ENDER = "Creature-0-1465-2175-71046-156942-0000000001"


def ender_scene(distance=50., *, soft=None, z=50., facing=0.):
    npc = unit(ENDER, distance, 0., z=z, npc_flags=2)
    return state(100., session_id="server-turnin", map_id=1409, orientation=facing,
        player_world_position={"x": 0., "y": 0., "z": 50., "z_observed": True,
                               "instance_id": 2175, "coordinate_space": "WORLD_YARDS"},
        active_quests=[{"quest_id": 42, "is_complete": True, "objectives": []}],
        reference_knowledge={"quests": {"42": {"quest_roles": [{"role": "QUEST_ENDER", "npc_id": 156942}]}}},
        packet_entities={ENDER: npc}, target={"guid": "previous-npc", "attackable": False},
        soft_targets=[{"source_unit": "softinteract", "guid": soft}] if soft else [],
        soft_targets_sample_time=100.)


def test_poi_move_yields_immediately_when_matching_server_ender_arrives():
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
    from wowbot.agent.models import Outcome
    from wowbot.runtime.verification_engine import VerificationEngine
    move = route(quest_id=42, x=500., y=0.)
    attempt = SimpleNamespace(proposal=move)
    live = ender_scene()
    for identity_only in (False, True):
        handoff = movement_visual_interrupt(attempt, live, identity_only=identity_only)
        assert handoff["kind"]=="SERVER_TURN_IN_ENTITY_AVAILABLE" and handoff["guid"]==ENDER
    supervisor = ActiveSkillSupervisor(m0_skills=None, verification_engine=VerificationEngine(),
        interaction_runtime=None, combat_runtime=None, loot_runtime=None, registry=None)
    result = supervisor._movement(attempt, live, None, "o", 100., None, handoff)
    assert result.terminal_outcome is Outcome.CANCELLED and result.stop_movement


def test_turnin_server_destination_replaces_poi_without_hover_or_hard_target():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy as QuestLocationPolicy
    live = ender_scene(200.)  # known entry: not artificially held to a 150-yard lookup
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    proposals = QuestLocationPolicy().propose_turnins(world.quest_model.records, live, {})
    p, = proposals
    assert p.skill=="MOVE" and p.parameters["server_entity_guid"]==ENDER
    assert p.parameters["x"]==200. and p.parameters["knowledge_priority"]=="SERVER_LIVE"
    assert p.parameters["require_navmesh"] and p.parameters["face_on_arrival"]


@pytest.mark.parametrize("old_visible", [False, True])
def test_unambiguous_server_reward_can_override_an_obsolete_ender_entry(old_visible):
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.turnin_resolver import TurnInResolver
    other = "Creature-0-1465-2175-71046-156833-0000000002"
    live = ender_scene()
    replacement = unit(other, 50., 0., npc_flags=2)
    replacement["quest_giver"] = {"reward_ready": True}
    if not old_visible:
        live["packet_entities"] = {}
    live["packet_entities"][other] = replacement
    before = deepcopy(live)
    resolved = TurnInResolver.server_ender(42, live)
    assert resolved["server_entity_guid"] == other
    assert resolved["quest_ender_basis"] == "UNIQUE_SERVER_REWARD_CANDIDATE"
    assert "server_reward_candidate_requires_quest_ui" in TurnInResolver().locate(
        SimpleNamespace(quest_id=42), live).evidence
    assert live == before  # a candidate is not a learned/verified role
    attempt = SimpleNamespace(proposal=route(quest_id=42, x=500., y=0.))
    assert movement_visual_interrupt(attempt, live, identity_only=True)["guid"] == other


@pytest.mark.parametrize("ambiguity", ["quests", "markers", "other_quest", "removed", "other_map"])
def test_unknown_server_reward_is_not_bound_to_a_quest_without_unambiguous_evidence(ambiguity):
    from wowbot.agent.turnin_resolver import TurnInResolver
    other = "Creature-0-1465-2175-71046-156833-0000000002"
    live = ender_scene()
    replacement = unit(other, 50., 0., npc_flags=2)
    replacement["quest_giver"] = {"reward_ready": True}
    live["packet_entities"] = {other: replacement}
    if ambiguity == "quests":
        live["active_quests"].append({"quest_id": 43, "is_complete": True})
    elif ambiguity == "markers":
        third = "Creature-0-1465-2175-71046-156834-0000000003"
        another = unit(third, 60., 0., npc_flags=2)
        another["quest_giver"] = {"reward_ready": True}
        live["packet_entities"][third] = another
    elif ambiguity == "other_quest":
        live["active_quests"][0]["quest_id"] = 43
    elif ambiguity == "removed":
        replacement["removed"] = {"reason": "OUT_OF_RANGE"}
    elif ambiguity == "other_map":
        replacement["map_id"] = 999
    assert TurnInResolver.server_ender(42, live) is None


def test_explicit_server_no_reward_overrides_a_historical_ender_position():
    from wowbot.agent.turnin_resolver import TurnInResolver
    live = ender_scene()
    live["packet_entities"][ENDER]["quest_giver"] = {"reward_ready": False, "quest_available": True}
    assert TurnInResolver.server_ender(42, live) is None


@pytest.mark.parametrize("changed_ender", [False, True])
def test_arrived_server_ender_is_f7_without_inspect_target_or_visual_search(changed_ender):
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy as QuestLocationPolicy
    from wowbot.skills import InteractSkill
    recipient = "Creature-0-1465-2175-71046-156833-0000000002" if changed_ender else ENDER
    live = ender_scene(3., soft=recipient)
    if changed_ender:
        replacement = unit(recipient, 3., 0., npc_flags=2)
        replacement["quest_giver"] = {"reward_ready": True}
        live["packet_entities"] = {recipient: replacement}
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    proposals = QuestLocationPolicy().propose_turnins(world.quest_model.records, live, {})
    p, = proposals
    assert p.skill=="INTERACT" and p.parameters["activation_source"]=="SOFT_INTERACT"
    assert p.parameters["soft_guid"]==recipient and SkillRegistry().available(p, world)
    from test_quest_dialog_fresh_evidence import _active
    running = _active(p, live, now=100.)
    result = InteractSkill().begin(running, live)
    assert result.status is SkillStatus.RUNNING
    assert [c.binding for c in result.commands]==["INTERACTTARGET"]
    attempt = SimpleNamespace(proposal=route(quest_id=42, x=3., y=0., knowledge_priority="SERVER_LIVE",
                                             server_entity_guid=recipient))
    assert movement_visual_interrupt(attempt, live, identity_only=True)["kind"]=="SERVER_TURN_IN_INTERACTION_READY"


@pytest.mark.parametrize("change", ["other_soft", "stale_soft", "facing", "floor", "hostile_soft"])
def test_server_turnin_never_presses_f7_at_wrong_stale_or_out_of_reach_recipient(change):
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy as QuestLocationPolicy
    live = ender_scene(3., soft=ENDER)
    if change=="other_soft": live["soft_targets"][0]["guid"]="other-npc"
    elif change=="stale_soft": live["soft_targets_sample_time"]=90.
    elif change=="facing": live["orientation"]=math.pi
    elif change=="floor": live["packet_entities"][ENDER]["position"]["z"]=70.
    elif change=="hostile_soft": live["soft_targets"][0]["is_attackable"]=True
    world = WorldModel()
    world.ingest(Observation.create(live, 100.))
    proposals = QuestLocationPolicy().propose_turnins(world.quest_model.records, live, {})
    assert proposals and all(p.skill=="MOVE" for p in proposals)
    assert not any(p.skill in {"SEEK_VISUAL_CUE", "INSPECT", "TARGET", "INTERACT"} for p in proposals)


def test_corpse_run_is_never_adapted_into_living_entrance_search():
    from wowbot.navigation import NavigationService
    p = Proposal.make("MOVE", "corpse", {"purpose": "CORPSE_RUN", "require_navmesh": True})
    world = SimpleNamespace(state={"is_ghost": True, "navigation_context": "CAVE"})
    result = NavigationSituationPolicy().adapt(p, world=world, navigation=NavigationService(),
        last_result={"skill": "MOVE", "outcome": "FAILURE", "reason": "supported_stuck"})
    assert result == p


def test_death_is_one_event_not_one_event_per_control_tick():
    sup = Supervisor()
    dead = {"is_dead": True}
    assert sup.evaluate(dead, None, 1.).event.event_type == "PLAYER_DIED"
    for t in (1.1, 2., 3.):
        d = sup.evaluate(dead, None, t)
        assert d.kind is SupervisorDirectiveKind.BLOCK and d.reason is FailureReason.PLAYER_DEAD
        assert d.event is None
    sup.evaluate({}, None, 4.)
    assert sup.evaluate(dead, None, 5.).event.event_type == "PLAYER_DIED"


def test_ghost_stuck_uses_validated_waypoint_and_a_finite_budget():
    policy = RecoveryPlanner()
    world = SimpleNamespace(state={"session_id": "s", "is_ghost": True,
        "player_world_position": {"x": 0., "y": 0., "instance_id": 2175}})
    p = Proposal.make("MOVE", "corpse", {"purpose": "CORPSE_RUN", "x": 100., "y": 10., "instance_id": 2175})
    calls = []
    nav = SimpleNamespace(mark_current_route_danger=lambda *a, **k: calls.append(k),
        new_local_recovery_waypoint=lambda *a: {"x": 3., "y": 1., "z": 5., "instance_id": 2175,
                                                "coordinate_space": "WORLD_YARDS"})
    def recover(index):
        return policy.apply(p, world=world, goal=None, navigation=nav, registry=None, autonomy=None,
            failures={}, now=100.+index, last_result={"skill": "MOVE", "outcome": "FAILURE",
            "reason": "supported_stuck", "action_id": f"failed-{index}"}).proposal
    for i in range(1, 4):
        result = recover(i)
        assert result.skill == "MOVE" and result.parameters["purpose"] == "CORPSE_RUN"
        assert result.parameters["require_navmesh"] and result.parameters["corpse_recovery_waypoint"]
    assert recover(4).skill == "WAIT"
    world.state["player_world_position"]["x"] = 8.  # actual movement permits a fresh recovery budget
    assert recover(5).skill == "MOVE"


def receipt_before():
    return {"session_id": "s:player", "character_guid": "Player-1", "transport_session": "s",
            "monotonic_time": 100., "event_sequence": 10, "events": [],
            "active_quests": [{"quest_id": 42, "is_complete": True}]}


def receipt_after():
    return {**receipt_before(), "monotonic_time": 102., "active_quests": [],
            "quest_turn_in_receipts": [{"quest_id": 42, "sequence": 11, "at": 101.}]}


def test_actual_turnin_receipt_verifies_even_after_volatile_events_are_overwritten():
    result = QuestDialogVerifier().evaluate(receipt_before(), receipt_after(), quest_id=42, action="COMPLETE")
    assert result.success and "turn_in_receipt:11" in result.evidence


@pytest.mark.parametrize("change", ["absent_only", "old_sequence", "old_time", "future_time", "wrong_quest",
                                   "session", "character", "transport", "nan", "malformed", "same_receipt"])
def test_disappearance_or_stale_foreign_receipt_is_not_quest_completion(change):
    before, after = receipt_before(), receipt_after()
    row = after["quest_turn_in_receipts"][0]
    if change == "absent_only": after.pop("quest_turn_in_receipts")
    elif change == "old_sequence": row["sequence"] = 10
    elif change == "old_time": row["at"] = 99.
    elif change == "future_time": row["at"] = 103.
    elif change == "wrong_quest": row["quest_id"] = 43
    elif change == "session": after["session_id"] = "new-session"
    elif change == "character": after["character_guid"] = "Player-other"
    elif change == "transport": after["transport_session"] = "new-transport"
    elif change == "nan": row["at"] = math.nan
    elif change == "malformed": row["sequence"] = True
    elif change == "same_receipt": before["quest_turn_in_receipts"] = deepcopy(after["quest_turn_in_receipts"])
    assert not QuestDialogVerifier().evaluate(before, after, quest_id=42, action="COMPLETE").success


def test_fast_receipt_updates_world_quest_lifecycle_and_is_deduplicated():
    assembler, world = PacketAssembler(), WorldModel()
    initial = receipt_before()
    initial.update(player_present=True, quest_turn_in_receipts=[])
    before_packet = assembler.feed("AIPC5|s|1|0|1|STATE|"+json.dumps(initial), 1100.)
    world.ingest(Observation.create(before_packet, 1100.))
    before = deepcopy(world.state)
    latest = {"monotonic_time": 102., "quest_turn_in_receipts": receipt_after()["quest_turn_in_receipts"]}
    for seq in (2, 3):
        packet = assembler.feed(f"AIPC5|s|{seq}|0|1|FAST|"+json.dumps(latest), 1102.+seq/10.)
        world.ingest(Observation.create(packet, 1102.+seq/10.), defer_rebuild=True)
        world.flush_pending()
    assert QuestDialogVerifier().evaluate(before, world.state, quest_id=42, action="COMPLETE").success
    record = next(q for q in world.quest_model.records.values() if str(q.quest_id)=="42")
    assert record.current_state == "TURNED_IN"
    assert len([e for e in world.events if e.get("event_type")=="QUEST_TURNED_IN"]) == 1


def test_lua_transport_preserves_receipt_in_full_and_bounded_fast_profiles():
    from test_agent_transport import lua_runtime
    for limit in (850, 3500):
        lua = lua_runtime()
        lua.execute('''data={monotonic_time=102,timestamp=1102,character_guid="Player-1",
          player_present=true,target=false,mouseover=false,soft_targets={},is_in_combat=false,
          quest_turn_in_receipts={{quest_id=42,sequence=11,at=101}}}''')
        packet, _ = lua.eval(f"ns.NextLanePackets(data,data,{limit},850)")
        assert packet is not None
        decoded = json.loads(packet.split("|", 6)[-1])
        assert decoded["quest_turn_in_receipts"][0]["quest_id"] == 42


def test_addon_retains_only_real_turnin_events_despite_hover_churn():
    from test_agent_transport import lua_runtime
    source = (Path(__file__).resolve().parents[1]/"addon/AIPlayerControllerExport/AIPlayerControllerExport.lua").read_text(encoding="utf-8")
    start, end = source.index("local function emitEvent("), source.index("local function initializeDatabase(")
    lua = lua_runtime()
    rows, reaccepted = lua.execute('''local eventSequence, latestEvent = 0, nil
      local questTurnInReceipts = {}
      local EVENT_HISTORY_LIMIT, PROTOCOL_VERSION, SCHEMA_VERSION, ADDON_VERSION=100,"AIPC5",4,"test"
      local function serverTimestamp() return 1100 end
      local function nowSeconds() return 101 end
      local function safeText(v,f) return v or f end
      local function safeNumber(v) return type(v)=="number" and v or 0 end
      local function sanitizeEventValue(v) return v end
    ''' + source[start:end] + '''
      emitEvent("QUEST_TURNED_IN", {quest_id=42}, "WOW_EVENT")
      for i=1,200 do emitEvent("MOUSEOVER_CHANGED", {}, "WOW_API") end
      emitEvent("QUEST_ABANDONED_OR_REMOVED", {quest_id=43}, "WOW_EVENT")
      local saved = readQuestTurnInReceipts(8)
      emitEvent("QUEST_ACCEPTED", {quest_id=42}, "WOW_EVENT")
      return saved, readQuestTurnInReceipts(8)
    ''')
    assert len(rows)==1 and rows[1]["quest_id"]==42 and rows[1]["sequence"]==1
    assert len(reaccepted)==0
