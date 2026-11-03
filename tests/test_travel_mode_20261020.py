"""Travel mode: mount only with a real mount + riding, no mount/dismount flapping.

User 2026-10-20: "mountolás csak akkor kéne legyen, ha egyáltalán van
mountunk, vagy van mount riding skillünk".  The live warrior (level 10,
2026-10-20 18:43-19:07) had no mount on any bar and no capability export;
it must keep walking.
"""
from types import SimpleNamespace

from test_agent_core import agent, state
from wowbot.agent.models import Proposal
from wowbot.agent.travel_mode import (FAILURE_SECONDS, REMOUNT_SECONDS, TravelModePolicy,
                                      mount_action)

CAPABLE = {"has_collected_mount": True, "riding_capability_confirmed": True,
           "source": "MOUNT_JOURNAL_AND_SPELLBOOK"}


def favorite_mount(**extra):
    return {"slot": 12, "action": "ACTIONBUTTON12", "binding_primary": "=", "binding_secondary": "",
            "kind": "summonmount", "id": 268435455, "is_usable": True, "cooldown_remaining": 0,
            **extra}


def world(now, *, x=0., mounted=False, last_result=None, **extra):
    values = {"monotonic_time": now, "is_mounted": mounted, "mount_capability": CAPABLE,
              "actionbar": [favorite_mount()],
              "player_world_position": {"x": x, "y": 0., "instance_id": 2444},
              **extra}
    return SimpleNamespace(state=values, runtime_context={"last_result": last_result})


def long_move(priority=50.):
    return Proposal.make("MOVE", "far", {"x": 200., "y": 0., "instance_id": 2444,
                                         "coordinate_space": "WORLD_YARDS"}, priority=priority)


GOAL = SimpleNamespace(parameters={})


def skills(proposals):
    return [p.skill for p in proposals]


def test_action_bar_mount_with_a_key_is_the_mount_binding():
    assert mount_action({}, {"actionbar": [favorite_mount()]})["action"] == "ACTIONBUTTON12"
    assert mount_action({}, {"actionbar": [favorite_mount(binding_primary="")]}) is None
    spell = {"action": "ACTIONBUTTON3", "kind": "spell", "binding_primary": "3"}
    assert mount_action({}, {"actionbar": [spell]}) is None
    # An explicit goal binding still wins.
    assert mount_action({"mount_binding": "ACTIONBUTTON3"}, {"actionbar": [spell]}) is spell


def test_long_move_rides_with_capability_and_a_bound_mount():
    policy = TravelModePolicy()
    result = policy.apply([long_move()], GOAL, world(1.), 1.)
    mount = next(p for p in result if p.skill == "MOUNT")
    assert mount.parameters["binding"] == "ACTIONBUTTON12"
    assert mount.priority > 50.
    assert policy.snapshot()["mode"] == "GROUND_MOUNT"


def test_no_mount_capability_keeps_walking():
    for capability in (None, {"has_collected_mount": False, "riding_capability_confirmed": True},
                       {"has_collected_mount": True, "riding_capability_confirmed": False}):
        policy = TravelModePolicy()
        result = policy.apply([long_move()], GOAL, world(1., mount_capability=capability), 1.)
        assert skills(result) == ["MOVE"]
        snapshot = policy.snapshot()
        assert snapshot.pop("transitions")["pending"] is None    # spec 30.2 machine, idle here
        assert snapshot.pop("travel_plan") is None                # spec 30.1: gated before planning
        assert snapshot == {"mode": "WALK", "reason": "no_mount_capability",
                                     "dismounted_at": None, "mount_failed_at": None,
                                     "flight_blockers": [], "flight_mount_wait_until": None}


def test_live_level_10_warrior_without_mount_keeps_walking():
    policy = TravelModePolicy()
    values = world(1.)
    values.state.pop("mount_capability")
    values.state["actionbar"] = [{"action": "ACTIONBUTTON1", "binding_primary": "1",
                                  "kind": "spell", "id": 100, "name": "Charge", "is_usable": False}]
    assert skills(policy.apply([long_move()], GOAL, values, 1.)) == ["MOVE"]


def test_short_move_unusable_action_and_unsafe_context_do_not_mount():
    near = Proposal.make("MOVE", "near", {"x": 20., "y": 0., "instance_id": 2444,
                                          "coordinate_space": "WORLD_YARDS"}, priority=50.)
    cases = [
        ([near], world(1.), "no_long_move"),
        ([long_move()], world(1., actionbar=[favorite_mount(is_usable=False)]), "mount_action_unusable"),
        ([long_move()], world(1., movement={"indoors": True}), "indoors"),
        ([long_move()], world(1., movement={"swimming": True}), "swimming"),
        ([long_move()], world(1., in_vehicle=True), "in_vehicle"),
        ([long_move()], world(1., is_in_combat=True), "in_combat"),
    ]
    for proposals, values, reason in cases:
        policy = TravelModePolicy()
        assert "MOUNT" not in skills(policy.apply(proposals, GOAL, values, 1.)), reason
        assert policy.reason == reason


def test_on_foot_action_ranked_with_the_route_is_not_delayed_by_a_mount():
    talk = Proposal.make("INTERACT", "npc", {"soft_guid": "npc-1"}, priority=55.)
    policy = TravelModePolicy()
    assert "MOUNT" not in skills(policy.apply([long_move(), talk], GOAL, world(1.), 1.))
    assert policy.reason == "on_foot_action_leads"


def test_mounted_route_keeps_the_mount_and_dismounts_only_for_on_foot_work():
    policy = TravelModePolicy()
    assert skills(policy.apply([long_move()], GOAL, world(1., mounted=True), 1.)) == ["MOVE"]
    assert policy.mode == "KEEP_CURRENT_MODE"
    loot = Proposal.make("LOOT", "corpse", {}, priority=108.)
    result = policy.apply([long_move(), loot], GOAL, world(2., mounted=True), 2.)
    dismount = next(p for p in result if p.skill == "DISMOUNT")
    assert dismount.parameters == {"binding": "ACTIONBUTTON12", "for_skill": "LOOT"}
    assert dismount.priority > loot.priority


def test_never_dismounts_in_the_air():
    policy = TravelModePolicy()
    loot = Proposal.make("LOOT", "corpse", {}, priority=108.)
    airborne = world(1., mounted=True, movement={"flying": True})
    assert "DISMOUNT" not in skills(policy.apply([long_move(), loot], GOAL, airborne, 1.))
    assert policy.reason == "airborne_no_dismount"


def test_no_remount_right_after_a_dismount():
    policy = TravelModePolicy()
    policy.apply([long_move()], GOAL, world(1., mounted=True), 1.)
    after = 2.
    assert "MOUNT" not in skills(policy.apply([long_move()], GOAL, world(after), after))
    assert policy.reason == "recently_dismounted"
    later = after + REMOUNT_SECONDS
    assert "MOUNT" in skills(policy.apply([long_move()], GOAL, world(later), later))


def test_failed_mount_is_not_retried_in_the_same_place():
    policy = TravelModePolicy()
    failed = {"skill": "MOUNT", "outcome": "FAILURE", "action_id": "a-1"}
    assert "MOUNT" not in skills(policy.apply([long_move()], GOAL, world(5., last_result=failed), 5.))
    assert policy.reason == "mount_failed_here"
    # The same result seen again does not restart the back-off.
    assert "MOUNT" not in skills(policy.apply([long_move()], GOAL, world(10., last_result=failed), 10.))
    moved = world(12., x=40., last_result=failed)
    assert "MOUNT" in skills(policy.apply([long_move()], GOAL, moved, 12.))
    later = 5. + FAILURE_SECONDS
    assert "MOUNT" in skills(policy.apply([long_move()], GOAL, world(later, last_result=failed), later))


def test_agent_mounts_from_the_action_bar_without_a_goal_binding():
    value, executor = agent("Menj oda", {"destination": {"map_id": 1609, "x": .5, "y": .44}})
    value.tick(state(actionbar=[favorite_mount()], is_mounted=False, mount_capability=CAPABLE), 1)
    assert value.pending.proposal.skill == "MOUNT"
    assert executor.commands[-1].binding == "ACTIONBUTTON12"
    assert value.status(1)["travel_mode"]["mode"] == "GROUND_MOUNT"


def test_a_long_walk_stops_once_to_mount_after_the_remount_wait():
    """User 2026-10-21 ("féluton szállt fel mountra"): 15:51:10 dismounted to
    loot, 15:51:17 a long turn-in walk started on foot (remount wait), the
    MOUNT came only with the next MOVE a minute later."""
    policy = TravelModePolicy()
    policy.apply([], GOAL, world(0., mounted=True), 0.)
    policy.apply([], GOAL, world(1.), 1.)                       # dismounted at 1 s
    walk = long_move()
    assert not policy.mount_now(walk, GOAL, world(10.), 10.)    # remount wait
    assert policy.mount_now(walk, GOAL, world(1.+REMOUNT_SECONDS+1.), 1.+REMOUNT_SECONDS+1.)
    assert not policy.mount_now(walk, GOAL, world(25.), 25.)    # one stop per 30 s
    near = Proposal.make("MOVE", "near", {"x": 60., "y": 0., "instance_id": 2444,
                                          "coordinate_space": "WORLD_YARDS"})
    assert not TravelModePolicy().mount_now(near, GOAL, world(100.), 100.)   # 60 yd left: keep walking
    assert not TravelModePolicy().mount_now(walk, GOAL, world(100., is_in_combat=True), 100.)


def test_attacked_on_the_mount_it_gets_off_to_fight():
    """Live 2026-10-26 14:14: mounted, attacked, DEFEND failed OUT_OF_RANGE
    over and over and the agent stood still."""
    from wowbot.runtime.supervisor import Supervisor
    policy = TravelModePolicy()
    defend = Proposal.make("DEFEND", "attacker", {"guid": "x"}, priority=100.)
    result = policy.apply([defend], GOAL, world(1., mounted=True, is_in_combat=True), 1.)
    dismount = next(p for p in result if p.skill == "DISMOUNT")
    assert dismount.priority > defend.priority and dismount.parameters["purpose"] == "COMBAT_DISMOUNT"
    assert Supervisor.combat_admissible("DISMOUNT", dismount.parameters)
    assert not Supervisor.combat_admissible("DISMOUNT", {"binding": "ACTIONBUTTON12"})


def test_attacked_in_the_air_it_lands_first_and_never_dismounts_there():
    from wowbot.runtime.supervisor import Supervisor
    policy = TravelModePolicy()
    defend = Proposal.make("DEFEND", "attacker", {"guid": "x"}, priority=100.)
    airborne = world(1., mounted=True, is_in_combat=True, movement={"flying": True})
    result = policy.apply([defend], GOAL, airborne, 1.)
    assert "DISMOUNT" not in skills(result)
    landing = next(p for p in result if p.skill == "MOVE")
    assert landing.parameters["purpose"] == "COMBAT_LANDING" and landing.priority > defend.priority
    assert Supervisor.combat_admissible("MOVE", landing.parameters)


def test_on_the_skyriding_bar_a_multi_bar_mount_is_the_dismount_key():
    sky = [{"action": "ACTIONBUTTON1", "kind": "spell", "name": "Surge Forward", "binding_primary": "1",
            "source": "SKYRIDING_BAR"},
           favorite_mount(action="MULTIACTIONBAR1BUTTON1", binding_primary="SHIFT-1")]
    assert mount_action({}, {"actionbar": sky})["action"] == "MULTIACTIONBAR1BUTTON1"


def test_no_mount_for_a_short_hop_between_quest_mobs():
    """Live 2026-10-26 14:13-14:23: a mount before every 40-60 yd hop."""
    policy = TravelModePolicy()
    hop = Proposal.make("MOVE", "next mob", {"x": 70., "y": 0., "instance_id": 2444,
                                             "coordinate_space": "WORLD_YARDS",
                                             "purpose": "APPROACH_SERVER_KILL_TARGET"}, priority=100.)
    assert "MOUNT" not in skills(policy.apply([hop], GOAL, world(1.), 1.))
    assert policy.reason == "hunting_nearby"
    far = Proposal.make("MOVE", "far mob", {**hop.parameters, "x": 300.}, priority=100.)
    assert "MOUNT" in skills(TravelModePolicy().apply([far], GOAL, world(1.), 1.))



def test_a_destination_far_below_counts_its_height_for_the_flight():
    """Live 2026-10-26 17:22: the turn-in 90 yd straight below a ledge."""
    from wowbot.agent.travel_mode import TravelModePolicy
    below = Proposal.make("MOVE", "turn-in", {"x": 1., "y": 0., "z": 95., "z_known": True, "instance_id": 2444,
                                              "coordinate_space": "WORLD_YARDS"}, priority=100.)
    state = world(1., mounted=True, flight={"can_glide": True, "advanced_flyable_area": True, "flyable_area": True},
                  movement={"indoors": False, "flying": False})
    state.state["player_world_position"] = {"x": 0., "y": 0., "z": 185.6, "z_observed": True, "instance_id": 2444}
    flown = TravelModePolicy().apply([below], GOAL, state, 1.)
    move = next(p for p in flown if p.skill == "MOVE")
    assert move.parameters.get("flight_style") == "SKYRIDING"


def test_a_target_high_above_is_flown_to_even_close_by():
    """Live 2026-10-27 17:03: the East Siege Arbalest on a bridge 44 yd above,
    1.6 yd away flat; no walking path up, the agent waited under it."""
    from wowbot.agent.travel_mode import TravelModePolicy
    arbalest = Proposal.make("MOVE", "linked object", {"x": 1.6, "y": 0., "z": 245.6, "z_known": True,
                                                       "instance_id": 2444, "coordinate_space": "WORLD_YARDS",
                                                       "purpose": "APPROACH_QUEST_OBJECT_SPAWN"}, priority=119.)
    state = world(1., mounted=True, flight={"can_glide": True, "advanced_flyable_area": True, "flyable_area": True},
                  movement={"indoors": False, "flying": False})
    state.state["player_world_position"] = {"x": 0., "y": 0., "z": 201., "z_observed": True, "instance_id": 2444}
    move = next(p for p in TravelModePolicy().apply([arbalest], GOAL, state, 1.) if p.skill == "MOVE")
    assert move.parameters.get("flight_style") == "SKYRIDING"
    state.state["player_world_position"]["z"] = 238.                  # 7.6 yd: a step up, walked
    move = next(p for p in TravelModePolicy().apply([arbalest], GOAL, state, 1.) if p.skill == "MOVE")
    assert move.parameters.get("flight_style") != "SKYRIDING"
