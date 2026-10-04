from wowbot.agent.autonomy_loop import AutonomousLoop, RuntimePhase
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.world import WorldModel
from test_agent_core import agent, state


def world(payload):
    value = WorldModel()
    value.ingest(Observation.create(payload, payload.get("timestamp", 1)))
    return value


def target_state(at=1, *, hp=100, dead=False, target=True, marker=False, current=0):
    unit = ({"guid": "mob-1", "npc_id": 111, "name": "Murloc",
             "attackable": True, "dead": dead, "health": hp, "max_health": 100,
             "quest_relevant": True,
             "screen_position": {"x": .5, "y": .5, "sample_time": at,
                                   "source": "NAMEPLATE_API",
                                   "coordinate_space": "CLIENT_BOTTOM_LEFT"}}
            if target else None)
    candidates = ([{"source": "WORLD3D", "track_id": "bush", "kind": "entity_candidate",
                    "stable_frames": 5, "confidence": .95, "x": .2, "y": .5}]
                  if marker else [])
    return state(at, target=unit, is_in_combat=bool(target and not dead),
                 active_quests=[{"quest_id": 42, "objectives": [{"objective_id": "42:kill",
                     "type": "KILL", "current": current, "required": 3,
                     "description": "Kill Murlocs"}]}],
                 actionbar=[{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                             "is_harmful": True, "is_usable": True, "in_range": True,
                             "cooldown_remaining": 0}], visual_candidates=candidates)


def test_committed_target_beats_unrelated_high_value_inspection():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    current = world(target_state())
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1", "objective_ids": ["42:kill"]}, priority=75)
    assert loop.choose([combat], combat, goal, current, 1).skill == "COMBAT"
    commitment_id = loop.commitment.commitment_id
    inspect = Proposal.make("INSPECT", "unrelated bush", {"x": .2, "y": .5}, priority=130)
    chosen = loop.choose([inspect, combat], inspect, goal, current, 2)
    assert chosen.skill == "COMBAT"
    assert loop.commitment.commitment_id == commitment_id
    assert loop.phase == RuntimePhase.COMBAT


def test_repeated_combat_actions_keep_plan_and_subgoal_identity():
    bot, executor = agent()
    first = bot.tick(target_state(1), 1)
    assert first["decision"]["skill"] == "COMBAT"
    plan_id = first["plan"]["plan_id"]
    commitment_id = first["autonomous_loop"]["commitment"]["commitment_id"]
    second = bot.tick(target_state(2, hp=90, marker=True), 2)
    assert second["decision"]["skill"] == "COMBAT"
    assert second["plan"]["plan_id"] == plan_id
    assert second["autonomous_loop"]["commitment"]["commitment_id"] == commitment_id
    assert all(command.kind != "HOVER" for command in executor.commands)


def test_target_death_transitions_same_commitment_to_loot():
    bot, _ = agent()
    first = bot.tick(target_state(1), 1)
    commitment_id = first["autonomous_loop"]["commitment"]["commitment_id"]
    result = bot.tick(target_state(2, hp=0, dead=True), 2)
    assert result["decision"]["skill"] == "LOOT"
    assert result["autonomous_loop"]["commitment"]["commitment_id"] == commitment_id
    assert result["autonomous_loop"]["phase"] == "INTERACTING"


def test_target_loss_needs_three_distinct_observations_before_replan():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    initial = world(target_state())
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1", "objective_ids": ["42:kill"]})
    loop.choose([combat], combat, goal, initial, 1)
    inspect = Proposal.make("INSPECT", "new unknown", {"x": .2, "y": .5}, priority=100)
    missing = world(target_state(2, target=False))
    assert loop.choose([inspect], inspect, goal, missing, 2).skill == "WAIT"
    assert loop.choose([inspect], inspect, goal, missing, 2.1).skill == "WAIT"  # same observation
    missing2 = world(target_state(3, target=False))
    assert loop.choose([inspect], inspect, goal, missing2, 3).skill == "WAIT"
    missing3 = world(target_state(4, target=False))
    assert loop.choose([inspect], inspect, goal, missing3, 4).skill == "INSPECT"
    assert loop.last_replan_trigger == "TARGET_LOST"


def test_quest_state_change_is_an_explicit_replan_trigger():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    initial = world(target_state(current=0))
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1", "objective_ids": ["42:kill"]})
    loop.choose([combat], combat, goal, initial, 1)
    changed = world(target_state(2, current=1))
    inspect = Proposal.make("INSPECT", "new evidence", {"x": .2, "y": .5})
    loop.choose([combat, inspect], combat, goal, changed, 2)
    assert loop.last_replan_trigger == "QUEST_STATE_CHANGED"
    assert loop.replan_revision == 1


def test_survival_interrupt_preempts_commitment_without_erasing_it():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    current = world(target_state())
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1", "objective_ids": ["42:kill"]}, priority=75)
    loop.choose([combat], combat, goal, current, 1)
    identity = loop.commitment.commitment_id
    escape = Proposal.make("ESCAPE", "fatal health", {"binding": "ACTIONBUTTON2"}, priority=125)
    assert loop.choose([combat, escape], combat, goal, current, 2).skill == "ESCAPE"
    assert loop.commitment.commitment_id == identity
    assert loop.lifecycle[-1]["event"] == "SAFETY_INTERRUPT"


def test_state_machine_blocks_committed_target_to_random_observing_transition():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    current = world(target_state())
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1", "objective_ids": ["42:kill"]})
    loop.choose([combat], combat, goal, current, 1)
    loop._set_phase(RuntimePhase.OBSERVING, 2, "random_unknown_appeared")
    assert loop.phase == RuntimePhase.COMBAT
    assert loop.lifecycle[-1]["event"] == "INVALID_TRANSITION_BLOCKED"


def test_committed_target_rejects_unrelated_inspect_and_camera_search():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    current = world(target_state())
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1"})
    loop.choose([combat], combat, goal, current, 1)
    inspect = Proposal.make("INSPECT", "unrelated scenery",
                            {"track_id": "WORLD3D:bush", "source": "WORLD3D"}, priority=130)
    camera = Proposal.make("CAMERA_CONTROL", "random scan",
                           {"camera_action": "SCAN_SECTOR"}, priority=140)
    assert loop.choose([inspect, camera, combat], camera, goal, current, 2).skill == "COMBAT"


def test_committed_target_allows_only_its_associated_track_inspection():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    payload = target_state()
    payload["target"]["screen_position"] = {"track_id": "WORLD3D:target"}
    current = world(payload)
    combat = Proposal.make("COMBAT", "goal target", {"guid": "mob-1"})
    loop.choose([combat], combat, goal, current, 1)
    inspect = Proposal.make("INSPECT", "same visual entity",
                            {"track_id": "WORLD3D:target", "source": "WORLD3D"}, priority=130)
    assert loop.choose([inspect, combat], inspect, goal, current, 2).skill == "INSPECT"


def test_unverified_target_click_keeps_confirmed_identity_for_reacquisition():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    current = world(target_state(target=False))
    target = Proposal.make("TARGET", "addon mouseover identity",
                           {"guid": "jaina", "x": .53, "y": .66})
    loop.choose([target], target, goal, current, 1)
    commitment_id = loop.commitment.commitment_id

    loop.outcome(target, False, "expected_observation_missing", current, 9)

    assert loop.commitment is not None
    assert loop.commitment.commitment_id == commitment_id
    assert loop.commitment.target_guid == "jaina"
    assert loop.last_replan_trigger != "SKILL_FAILED"
    assert loop.lifecycle[-1]["event"] == "TARGET_REACQUIRE_REQUIRED"


def test_unobserved_interaction_keeps_exact_selected_target_committed():
    loop = AutonomousLoop()
    goal = Goal.parse("Questelj", 1)
    payload = target_state(target=False)
    payload["target"] = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
                         "attackable": False, "dead": False}
    current = world(payload)
    interact = Proposal.make("INTERACT", "selected friendly target", {"guid": "jaina"})
    loop.choose([interact], interact, goal, current, 1)
    commitment_id = loop.commitment.commitment_id

    loop.outcome(interact, False, "expected_observation_missing", current, 8)

    assert loop.commitment is not None
    assert loop.commitment.commitment_id == commitment_id
    assert loop.commitment.target_guid == "jaina"
    assert loop.lifecycle[-1]["event"] == "INTERACTION_RANGE_CANDIDATE"
