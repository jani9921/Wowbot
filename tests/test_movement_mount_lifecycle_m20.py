from types import SimpleNamespace

from test_agent_core import agent, state
from wowbot.agent.models import Proposal
from wowbot.agent.skills import SkillRegistry


MOUNT_BINDING = "ACTIONBUTTON12"


def mount_capability(*, owned=True, riding=True):
    return {
        "has_collected_mount": owned,
        "riding_capability_confirmed": riding,
        "source": "MOUNT_JOURNAL_AND_SPELLBOOK",
    }


def mount_action():
    return {"kind": "spell", "id": 1234, "name": "Test Mount",
            "action": MOUNT_BINDING, "is_usable": True,
            "cooldown_remaining": 0}


def test_long_move_mounts_then_verified_state_continues_with_move():
    value, executor = agent("Menj oda", {
        "destination": {"map_id": 1609, "x": .5, "y": .44},
        "mount_binding": MOUNT_BINDING,
    })
    value.tick(state(actionbar=[mount_action()], is_mounted=False,
                     mount_capability=mount_capability()), 1)
    assert value.pending.proposal.skill == "MOUNT"
    assert executor.commands[-1].binding == MOUNT_BINDING

    value.tick(state(2, actionbar=[mount_action()], is_mounted=True,
                     mount_capability=mount_capability()), 2)
    assert value.last_result["skill"] == "MOUNT"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.pending.proposal.skill == "MOVE"
    assert executor.commands[-1].binding == "MOVEFORWARD"


def test_mounted_agent_dismounts_before_confirmed_on_foot_interaction():
    value, executor = agent("Questelj", {"mount_binding": MOUNT_BINDING})
    friendly = {"guid": "npc-1", "name": "Guide", "attackable": False, "dead": False}
    value.tick(state(target=friendly, is_mounted=True), 1)
    assert value.pending.proposal.skill == "DISMOUNT"
    assert value.pending.proposal.parameters["for_skill"] == "INTERACT"
    assert executor.commands[-1].binding == MOUNT_BINDING

    value.tick(state(2, target=friendly, is_mounted=False), 2)
    assert value.last_result["skill"] == "DISMOUNT"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.pending.proposal.skill == "INTERACT"
    assert executor.commands[-1].binding == "INTERACTTARGET"


def test_dismount_requires_observed_mounted_to_unmounted_transition():
    value, _ = agent("Questelj", {"mount_binding": MOUNT_BINDING})
    friendly = {"guid": "npc-1", "name": "Guide", "attackable": False, "dead": False}
    value.tick(state(target=friendly, is_mounted=True), 1)
    value.tick(state(2, target=friendly, is_mounted=True), 2)
    assert value.pending.proposal.skill == "DISMOUNT"
    # The DISMOUNT contract waits 5 s (live 16:37:41: the dismount arrived
    # ~3.8 s after the press); still mounted after that is a failure.
    value.tick(state(8, target=friendly, is_mounted=True), 8)
    assert value.last_result["skill"] == "DISMOUNT"
    assert value.last_result["outcome"] == "FAILURE"


def test_mounted_long_route_is_not_interrupted_without_on_foot_action():
    value, executor = agent("Menj oda", {
        "destination": {"map_id": 1609, "x": .5, "y": .44},
        "mount_binding": MOUNT_BINDING,
    })
    value.tick(state(is_mounted=True), 1)
    assert value.pending.proposal.skill == "MOVE"
    assert executor.commands[-1].binding == "MOVEFORWARD"


def test_long_move_does_not_mount_when_capability_telemetry_is_missing():
    value, executor = agent("Menj oda", {
        "destination": {"map_id": 1609, "x": .5, "y": .44},
        "mount_binding": MOUNT_BINDING,
    })
    value.tick(state(actionbar=[mount_action()], is_mounted=False), 1)
    assert value.pending.proposal.skill == "MOVE"
    assert executor.commands[-1].binding == "MOVEFORWARD"


def test_long_move_does_not_mount_without_owned_mount_and_riding_capability():
    for capability in (
        mount_capability(owned=False, riding=True),
        mount_capability(owned=True, riding=False),
    ):
        value, executor = agent("Menj oda", {
            "destination": {"map_id": 1609, "x": .5, "y": .44},
            "mount_binding": MOUNT_BINDING,
        })
        value.tick(state(actionbar=[mount_action()], is_mounted=False,
                         mount_capability=capability), 1)
        assert value.pending.proposal.skill == "MOVE"
        assert executor.commands[-1].binding == "MOVEFORWARD"


def test_dispatch_rechecks_mount_capability_but_dismount_remains_available():
    registry = SkillRegistry()
    mount = Proposal.make("MOUNT", "test", {"binding": MOUNT_BINDING})
    dismount = Proposal.make("DISMOUNT", "test", {"binding": MOUNT_BINDING})
    missing = SimpleNamespace(state=state(is_mounted=False))
    confirmed = SimpleNamespace(state=state(
        is_mounted=False, mount_capability=mount_capability()))
    already_mounted = SimpleNamespace(state=state(is_mounted=True))
    assert registry.available(mount, missing) is False
    assert registry.available(mount, confirmed) is True
    assert registry.available(dismount, already_mounted) is True
