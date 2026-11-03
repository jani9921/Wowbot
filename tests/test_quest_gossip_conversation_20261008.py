from adapters.telemetry_packets import normalize
from wowbot.agent.models import Attempt, Goal, Observation, Prediction, Proposal
from wowbot.agent.planner import QuestDomain
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.skills import QuestDialogSkill
from wowbot.verification.quest_dialog import QuestDialogVerifier


def _state():
    option = {"id": 917, "name": "I'm ready to fight you", "x": .24, "y": .71}
    return {"session_id": "test", "monotonic_time": 2., "quest_ui_open": True,
            "quest_ui_action": "GOSSIP_OPTION_SELECT",
            "quest_ui": {"open": True, "action": "GOSSIP_OPTION_SELECT",
                         "x": .24, "y": .71, "gossip_option": option},
            "target": {"guid": "Creature-Hjalmar", "name": "Hjalmar the Undying",
                       "attackable": False},
            "active_quests": [{"quest_id": 58915, "is_complete": False,
                               "objectives": [{"description":
                                               "0/1 Hjalmar the Undying slain with Execute"}]}]}


def _active(params, before):
    proposal = Proposal.make("QUEST_DIALOG", "conversation", params)
    attempt = Attempt("action", proposal, {}, "obs", 1., 10., (),
                      Prediction("prediction", "action", "state", 1., 10., "obs"))
    return ActiveSkillRuntime().start(intent=Intent("QUEST_DIALOG", params),
                                      attempt=attempt, now=1., before_snapshot=before)


def test_hjalmar_conversation_is_proposed_only_for_matching_active_objective():
    model = WorldModel()
    model.state = _state()
    proposals = QuestDomain().propose(model, Goal.parse("Questelj", 1.))
    assert proposals[0].skill == "QUEST_DIALOG"
    dialog = next(p for p in proposals if p.skill == "QUEST_DIALOG")
    assert dialog.parameters["action"] == "GOSSIP_OPTION_SELECT"
    assert dialog.parameters["quest_id"] == 58915
    assert dialog.parameters["gossip_option_id"] == 917
    assert dialog.parameters["target_guid"] == "Creature-Hjalmar"

    model.state = _state()
    model.state["target"]["name"] = "Kee-La"
    assert not any(p.skill == "QUEST_DIALOG" for p in QuestDomain().propose(model, None))


def test_conversation_click_rechecks_option_and_requires_fight_transition():
    before = _state()
    params = {"action": "GOSSIP_OPTION_SELECT", "quest_id": 58915,
              "x": .24, "y": .71, "target_guid": "Creature-Hjalmar",
              "gossip_option_id": 917, "gossip_option_name": "I'm ready to fight you"}
    skill = QuestDialogSkill()
    active = _active(params, before)
    started = skill.begin(active, before)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].kind == "CLICK"
    assert skill.verify(active, before, 2.).status is SkillStatus.RUNNING
    after = _state()
    after["quest_ui"] = {"open": False, "action": ""}
    after["target"]["attackable"] = True
    verified = skill.verify(active, after, 3.)
    assert verified.status is SkillStatus.SUCCESS
    assert verified.evidence == ("gossip_option_advanced:58915:917",)

    changed = _state()
    changed["quest_ui"]["gossip_option"]["id"] = 918
    assert skill.begin(_active(params, before), changed).commands == ()
    changed = _state()
    changed["target"]["guid"] = "Creature-Other"
    assert skill.begin(_active(params, before), changed).commands == ()


def test_closed_gossip_without_fight_is_not_confirmation():
    before = _state()
    after = _state()
    after["quest_ui"] = {"open": False, "action": ""}
    result = QuestDialogVerifier().evaluate(
        before, after, quest_id=58915, action="GOSSIP_OPTION_SELECT",
        target_guid="Creature-Hjalmar", gossip_option_id=917)
    assert not result.success


def test_fast_packet_keeps_option_and_clears_it_when_dialog_changes():
    model = WorldModel()
    option = {"id": 917, "name": "I'm ready to fight you", "x": .24, "y": .71}
    full = {"session_id": "test", "timestamp": .5, "frame_id": "full-1",
            "player_present": True, "monotonic_time": .5, "transport_kind": "STATE",
            "active_quests": _state()["active_quests"]}
    assert model.ingest(Observation.create(normalize(full), .5, source="ADDON_TELEMETRY"))
    packet = {"session_id": "test", "timestamp": 1., "frame_id": "fast-1",
              "player_present": True, "monotonic_time": 1., "transport_kind": "FAST",
              "target": {"guid": "Creature-Hjalmar", "name": "Hjalmar the Undying"},
              "quest_ui": {"open": True, "action": "GOSSIP_OPTION_SELECT",
                           "x": .24, "y": .71, "quest_id": 0, "gossip_option": option}}
    normalize(packet)
    assert model.ingest(Observation.create(packet, 1., source="ADDON_TELEMETRY"))
    assert model.state["quest_ui"]["gossip_option"] == option

    closed = {"session_id": "test", "timestamp": 2., "frame_id": "fast-2",
              "player_present": True, "monotonic_time": 2., "transport_kind": "FAST",
              "quest_ui": {"open": False, "action": "", "x": 0, "y": 0,
                           "quest_id": 0}}
    normalize(closed)
    assert model.ingest(Observation.create(closed, 2., source="ADDON_TELEMETRY"))
    assert model.state["quest_ui"]["gossip_option"] is None


def test_noncombat_gossip_verifies_only_matching_quest_progress_not_just_ui_close():
    from copy import deepcopy
    before = _state()
    before["active_quests"][0]["objectives"][0].update(current=0, required=1)
    before["quest_digest"] = [{"id": 58915, "done": 0, "need": 1}]
    after = deepcopy(before)
    after["quest_ui"] = {"open": False, "action": ""}
    verifier = QuestDialogVerifier()
    kwargs = dict(quest_id=58915, action="GOSSIP_OPTION_SELECT",
                  target_guid="Creature-Hjalmar", gossip_option_id=917,
                  gossip_transition="QUEST_PROGRESS")
    assert not verifier.evaluate(before, after, **kwargs).success
    after["is_in_combat"] = True
    assert not verifier.evaluate(before, after, **kwargs).success
    after["quest_digest"] = [{"id": 100, "done": 1, "need": 1}]
    assert not verifier.evaluate(before, after, **kwargs).success
    after["quest_digest"] = [{"id": 58915, "done": 1, "need": 1}]
    # Completing a conversation can clear the selected NPC; credit is the
    # authority, not keeping the old selection forever after the spell.
    after["target"] = {}
    verified = verifier.evaluate(before, after, **kwargs)
    assert verified.success and "quest_digest_progress:58915" in verified.evidence


def test_conversation_waits_without_input_through_phasing_until_delayed_credit():
    from copy import deepcopy
    before = _state()
    before["active_quests"][0]["objectives"][0].update(current=0, required=1)
    params = {"action": "GOSSIP_OPTION_SELECT", "quest_id": 58915,
              "x": .24, "y": .71, "target_guid": "Creature-Hjalmar",
              "gossip_option_id": 917, "gossip_option_name": "I'm ready to fight you",
              "gossip_transition": "QUEST_PROGRESS"}
    active = _active(params, before)
    skill = QuestDialogSkill()
    assert len(skill.begin(active, before).commands) == 1
    after = deepcopy(before)
    after["quest_ui"] = {"open": False, "action": ""}
    after["target"]["guid"] = "Creature-new-phase"
    # A new spawn is not the old identity. The already-issued action waits
    # only for quest evidence and must emit no further command.
    for now in (2., 5., 8.):
        result = skill.verify(active, after, now)
        assert result.status is SkillStatus.RUNNING and result.commands == ()
        assert active.skill_context["quest_dialog"]["target_guid"] == "Creature-Hjalmar"
    after["active_quests"][0]["objectives"][0].update(current=1, is_complete=True)
    verified = skill.verify(active, after, 9.)
    assert verified.status is SkillStatus.SUCCESS and verified.commands == ()
    # Without credit even a same-name replacement cannot verify success.
    after["active_quests"][0]["objectives"][0].update(current=0, is_complete=False)
    assert skill.verify(active, after, 11.).status is SkillStatus.FAILURE
