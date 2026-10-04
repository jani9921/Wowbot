from wowbot.agent.planner import QuestDomain
from wowbot.agent.world import WorldModel


def base_state(**overrides):
    state = dict(map_id=1409, session_id="test", monotonic_time=1,
                 active_quests=[], mouseover={}, quest_locations=[])
    state.update(overrides)
    return state


def friendly_target(guid="jaina", **overrides):
    target = dict(guid=guid, npc_id=156626, name="Lady Jaina Proudmoore",
                  unit_type="NPC", attackable=False, is_dead=False)
    target.update(overrides)
    return target


def propose(state):
    world = WorldModel()
    world.state = state
    return QuestDomain().propose(world, None)


def test_first_contact_with_a_freshly_selected_friendly_target_is_still_interacted_with():
    # Deliberately broad and unchanged: whatever unit is currently the live
    # target is worth one INTERACT before falling back to anything else, even
    # with no quest_role known yet (see test_agent_core.py's
    # test_confirmed_friendly_target_is_interacted_with_before_opening_map).
    # The actual fix here is interacted_guids below, not narrowing this.
    state = base_state(target=friendly_target())
    proposals = propose(state)
    assert any(p.skill == "INTERACT" for p in proposals)


def test_known_quest_giver_role_is_approached():
    state = base_state(target=friendly_target(quest_role="QUEST_GIVER"))
    proposals = propose(state)
    assert any(p.skill == "INTERACT" for p in proposals)


def test_fresh_mouseover_match_is_approached():
    state = base_state(target=friendly_target(), mouseover={"guid": "jaina"})
    proposals = propose(state)
    assert any(p.skill == "INTERACT" for p in proposals)


def test_already_interacted_guid_is_not_reproposed_at_same_quest_signature():
    state = base_state(target=friendly_target(quest_role="QUEST_GIVER"))
    domain = QuestDomain()
    domain.interacted_guids["jaina"] = WorldModel.quest_signature(state)
    world = WorldModel()
    world.state = state
    proposals = domain.propose(world, None)
    assert not any(p.skill == "INTERACT" for p in proposals)


def test_interact_reproposed_once_quest_signature_changes():
    state = base_state(target=friendly_target(quest_role="QUEST_GIVER"))
    domain = QuestDomain()
    # Recorded as already handled while no quest was active yet.
    domain.interacted_guids["jaina"] = WorldModel.quest_signature(state)
    # A quest just got accepted -- the signature changes, so the gate lifts.
    state["active_quests"] = [{"quest_id": 55122, "is_complete": False,
                               "objectives": [{"current": 0, "is_complete": False}]}]
    world = WorldModel()
    world.state = state
    proposals = domain.propose(world, None)
    assert any(p.skill == "INTERACT" for p in proposals)


def test_friendly_interact_gate_survives_brief_detail_flicker_but_expires():
    """Live repro: quest detail flickers, while an old [] gate must expire."""
    domain = QuestDomain()
    world = WorldModel()
    empty = base_state(target=friendly_target())
    world.state = empty
    assert any(p.skill == "INTERACT" for p in domain.propose(world, None))
    domain.interacted_guids["jaina"] = WorldModel.quest_signature(empty)
    domain.interacted_at["jaina"] = 1.
    assert not any(p.skill == "INTERACT" for p in domain.propose(world, None))

    world.state = base_state(active_quests=[{
        "quest_id": 55122, "is_complete": False,
        "objectives": [{"current": 0, "is_complete": False}],
    }])
    domain.propose(world, None)

    # A brief return to [] is a known detail-lane flicker, not a new contact.
    world.state = base_state(monotonic_time=10., target=friendly_target())
    assert not any(p.skill == "INTERACT" for p in domain.propose(world, None))

    # Much later, the same serialized signature cannot permanently blacklist
    # a freshly selected quest giver (live interval was about 146 seconds).
    world.state = base_state(monotonic_time=147., target=friendly_target())
    proposals = domain.propose(world, None)
    assert any(p.skill == "INTERACT" for p in proposals)
    assert not any(p.skill == "OPEN_MAP" for p in proposals)


def test_unresponsive_friendly_npc_is_not_reinteracted_or_retargeted_until_expiry():
    """Live 2026-09-30: a marker-less Kee-La was re-targeted and re-interacted."""
    domain = QuestDomain()
    world = WorldModel()
    kee_la = friendly_target(guid="kee-la", npc_id=156612, name="Kee-La")
    world.state = base_state(monotonic_time=100., target=kee_la)
    domain.unresponsive_guids["kee-la"] = (WorldModel.quest_signature(world.state), 100.)
    assert not any(p.skill == "INTERACT" for p in domain.propose(world, None))

    # Hovering the same NPC again (while another unit is selected) must not
    # hand it back to TARGET.
    world.state = base_state(
        monotonic_time=120., mouseover_sample_time=120., cursor_sample_time=120.,
        target={}, cursor_position={"nx": .5, "ny": .5},
        mouseover={"guid": "kee-la", "npc_id": 156612, "unit_type": "NPC", "attackable": False})
    assert domain.target_policy.propose(
        world, None, target={}, cursor_matches_mouseover=True, state_time=120., mouse_time=120.,
        skip_friendly_guids=domain.unresponsive_guid_set(world.state, 120.)) == []
    assert domain.target_policy.propose(
        world, None, target={}, cursor_matches_mouseover=True, state_time=120., mouse_time=120.)[0].skill == "TARGET"

    # Bounded: after the window, or once the quest state changes, it is eligible again.
    world.state = base_state(monotonic_time=401., target=kee_la)
    assert any(p.skill == "INTERACT" for p in domain.propose(world, None))
    domain.unresponsive_guids["kee-la"] = ("older-signature", 400.)
    world.state = base_state(monotonic_time=410., target=kee_la)
    assert any(p.skill == "INTERACT" for p in domain.propose(world, None))
