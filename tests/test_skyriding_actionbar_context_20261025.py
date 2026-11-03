"""Active Skyriding bar, cache authority, and return-to-ground regressions."""
from copy import deepcopy
import json

import pytest

from adapters.telemetry_packets import PacketAssembler
from wowbot.agent.bindings import BindingsCache
from wowbot.agent.binding_inventory import BindingInventory
from wowbot.agent.models import Observation
from wowbot.agent.runtime import AgentRuntime
from wowbot.agent.world import WorldModel
from test_agent_transport import _load_main_addon, lua_runtime


NORMAL = {"page": 1, "kind": "NORMAL", "revision": 1}
SKY = {"page": 11, "kind": "SKYRIDING", "revision": 2}
PLAYER = [{"slot": 10, "action": "ACTIONBUTTON10", "id": 999,
           "name": "Ground combat", "kind": "spell", "is_harmful": True}]
SKY_BAR = {"page": 11, "kind": "SKYRIDING", "revision": 2, "actions": [
    {"slot": 121, "index": 1, "action": "ACTIONBUTTON1", "id": 372608,
     "name": "Surge Forward", "kind": "spell", "is_usable": False,
     "is_harmful": False, "cooldown_remaining": 5}]}
FLIGHT_KEYS = {"MOVEFORWARD": "W", "PITCHUP": "INSERT", "PITCHDOWN": "DELETE", "TURNLEFT": "A",
               "TURNRIGHT": "D", "JUMP": "SPACE"}


def snapshot(at=1., **extra):
    return {"session_id": "sky-test", "timestamp": at, "monotonic_time": at,
            "frame_id": str(at), "transport_kind": "STATE", "player_present": True,
            "is_mounted": True, "in_vehicle": False, "on_taxi": False,
            "actionbar": deepcopy(PLAYER), "actionbar_context": deepcopy(SKY),
            "actionbar_snapshot_context": deepcopy(SKY),
            "skyriding_bar": deepcopy(SKY_BAR), **extra}


def world(**extra):
    result = WorldModel()
    result.ingest(Observation.create(snapshot(**extra), 1.))
    return result


def cache(tmp_path, *, omit=()):
    path = tmp_path / "bindings.wtf"
    path.write_text("\n".join(f'bind "{key}" "{action}"'
                              for action, key in FLIGHT_KEYS.items() if action not in omit)
                    + '\nbind "0" "ACTIONBUTTON10"\nbind "1" "ACTIONBUTTON1"\n')
    return BindingsCache(path)


def test_world_publishes_active_skyriding_actions_without_vehicle_semantics():
    state = world().state
    assert [a["name"] for a in state["actionbar"]] == ["Surge Forward"]
    assert state["skyriding_controls"] is True and state["vehicle_controls"] is False
    assert state["player_actionbar"][0]["name"] == "Ground combat"


def test_skyriding_projection_keeps_independently_bound_sidebars():
    side = {"slot": 61, "action": "MULTIACTIONBAR1BUTTON1", "id": 55, "kind": "summonmount"}
    state = world(actionbar=[*PLAYER, side]).state
    assert [a["action"] for a in state["actionbar"]] == ["ACTIONBUTTON1", "MULTIACTIONBAR1BUTTON1"]


def test_skyriding_fast_facts_refresh_the_active_ability():
    state = world(actionbar_fast=[[372608, True, True, 0]]).state
    assert state["actionbar"][0]["is_usable"] is True
    assert state["actionbar"][0]["cooldown_remaining"] == 0


@pytest.mark.parametrize("context", [False, {}, {**SKY, "page": True}, {**SKY, "revision": -1}])
def test_unknown_context_drops_retained_abilities(context):
    model = world()
    model.ingest(Observation.create(snapshot(2., transport_kind="FAST", actionbar_context=context), 2.))
    assert model.state["actionbar"] == []
    assert model.state["skyriding_controls"] is False


def test_action_projection_does_not_mutate_original_observation():
    model = WorldModel()
    observation = Observation.create(snapshot(), 1.)
    before = deepcopy(observation.payload)
    model.ingest(observation)
    assert observation.payload == before


@pytest.mark.parametrize("bar", [False, {**SKY_BAR, "page": 12}, {**SKY_BAR, "revision": 1}])
def test_missing_or_outdated_skyriding_bar_cannot_reactivate_ground_spells(bar):
    assert world(skyriding_bar=bar).state["actionbar"] == []


def test_explicit_dismount_rejects_a_retained_skyriding_bar():
    state = world(is_mounted=False).state
    assert state.get("skyriding_controls") is False
    assert not any(a.get("name") == "Surge Forward" for a in state.get("actionbar", []))


@pytest.mark.parametrize("deferred", [False, True])
def test_fast_bar_change_invalidates_old_actions_until_matching_full_snapshot(deferred):
    model = world()
    changed = {**SKY, "revision": 3}
    model.ingest(Observation.create(snapshot(2., transport_kind="FAST", actionbar_context=changed,
                                             actionbar_fast=[[372608, True, True, 0]]), 2.),
                 defer_rebuild=deferred)
    assert model.state["actionbar"] == []
    fresh_bar = {**SKY_BAR, "revision": 3}
    model.ingest(Observation.create(snapshot(3., actionbar_context=changed,
                                             actionbar_snapshot_context=changed,
                                             skyriding_bar=fresh_bar), 3.))
    assert model.state["actionbar"][0]["name"] == "Surge Forward"


def test_normal_full_snapshot_restores_combat_actions_after_dismount():
    model = world()
    normal = {**NORMAL, "revision": 3}
    model.ingest(Observation.create(snapshot(2., transport_kind="FAST", is_mounted=False,
                                             actionbar_context=normal), 2.))
    assert not model.state.get("skyriding_controls")
    assert model.state["actionbar"] == []
    model.ingest(Observation.create(snapshot(3., is_mounted=False, actionbar_context=normal,
                                             actionbar_snapshot_context=normal,
                                             skyriding_bar=False), 3.))
    assert model.state["actionbar"][0]["name"] == "Ground combat"


def test_runtime_preflight_ignores_ground_only_mismatch_in_skyriding(tmp_path):
    selected = cache(tmp_path)
    inventory = BindingInventory(tmp_path, selected, 42)
    inventory.control_bindings = {action: {"primary": key} for action, key in FLIGHT_KEYS.items()}
    inventory.supported = True
    inventory.report = {"complete": True, "bindings": [
        {"action": "ACTIONBUTTON10", "primary": "", "secondary": ""}]}
    from types import SimpleNamespace
    subject = SimpleNamespace(
        bindings=selected, binding_inventory=inventory,
        agent=SimpleNamespace(goal=SimpleNamespace(domain="QUEST"), world=SimpleNamespace(state=snapshot())))
    original = selected.path.read_bytes()
    check = AgentRuntime._binding_preflight(subject)
    assert check["ready"] is True and check["binding_mismatches"] == []
    assert selected.path.read_bytes() == original
    subject.agent.world.state = snapshot(is_mounted=False, actionbar_context=NORMAL)
    normal = AgentRuntime._binding_preflight(subject)
    assert normal["ready"] is False
    assert any(row["action"] == "ACTIONBUTTON10" for row in normal["binding_mismatches"])


def test_runtime_preflight_still_rejects_real_skyriding_control_mismatch(tmp_path):
    selected = cache(tmp_path)
    inventory = BindingInventory(tmp_path, selected, 42)
    inventory.control_bindings = {action: {"primary": key} for action, key in FLIGHT_KEYS.items()}
    inventory.control_bindings["PITCHUP"] = {"primary": "HOME"}
    from types import SimpleNamespace
    subject = SimpleNamespace(bindings=selected, binding_inventory=inventory,
        agent=SimpleNamespace(goal=SimpleNamespace(domain="QUEST"), world=SimpleNamespace(state=snapshot())))
    check = AgentRuntime._binding_preflight(subject)
    assert check["ready"] is False
    assert check["binding_mismatches"] == [
        {"action": "PITCHUP", "client": ["HOME"], "selected_cache": ["INSERT"]}]


def test_missing_pitch_binding_is_not_filled_from_client_or_default(tmp_path):
    from types import SimpleNamespace
    selected = cache(tmp_path, omit=("PITCHUP",))
    inventory = BindingInventory(tmp_path, selected, 42)
    subject = SimpleNamespace(bindings=selected, binding_inventory=inventory,
        agent=SimpleNamespace(goal=SimpleNamespace(domain="QUEST"), world=SimpleNamespace(state=snapshot())))
    assert "PITCHUP" in AgentRuntime._binding_preflight(subject)["missing"]


@pytest.mark.parametrize("incoming", [SKY, NORMAL])
def test_runtime_transition_validates_incoming_bar_before_the_previous_world(tmp_path, monkeypatch, incoming):
    from test_agent_runtime import Sensor
    from wowbot.agent.executor import RecordingExecutor
    from wowbot.agent.models import Mode

    selected = cache(tmp_path)
    sensor, executor = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, selected.path, tmp_path / "output", sensor=sensor,
                           executor=executor, vision=False)
    try:
        runtime.agent.set_goal("Questelj", 1.)
        previous = NORMAL if incoming == SKY else SKY
        runtime.agent.world.ingest(Observation.create(snapshot(
            actionbar_context=previous, actionbar_snapshot_context=previous), 1.))
        runtime.agent.set_mode(Mode.FULL_AI)
        # Isolate the receive-time cancellation guard; no planner/input runs.
        monkeypatch.setattr(runtime.agent, "tick", lambda *args: runtime.agent.status(2.))
        sensor.payload = snapshot(2., actionbar_context=incoming,
                                  actionbar_snapshot_context=incoming,
                                  control_bindings={
                                      **{a: {"primary": k} for a, k in FLIGHT_KEYS.items()},
                                      "ACTIONBUTTON10": {"primary": ""}})
        runtime.step(2.)
        assert runtime.agent.mode == (Mode.FULL_AI if incoming == SKY else Mode.MANUAL)
        assert executor.commands == []
    finally:
        runtime.close()


def test_lua_reads_skyriding_page_instead_of_hidden_ground_slots():
    lua = _load_main_addon('''
        function IsMounted() return true end
        function GetBonusBarOffset() return 5 end
        function GetActionBarPage() return 1 end
        C_ActionBar.GetActionInfo=function(slot)
            if slot==1 then return "spell",100 end
            if slot==121 then return "spell",372608 end
        end
    ''')
    full = json.loads(lua.eval('ns.EncodeJSON(AIPlayerControllerExportDB.latest)'))
    assert full["actionbar_context"]["kind"] == "SKYRIDING"
    assert full["skyriding_bar"]["page"] == 11
    assert full["skyriding_bar"]["actions"][0]["id"] == 372608
    ground = next(a for a in full["actionbar"] if a["slot"] == 1)
    assert not ground.get("action")
    lua.execute('''
        local original=ns.NextPacket
        ns.NextPacket=function(data,fast) captured_fast=fast; return original(data,fast) end
        local lanes=ns.NextLanePackets
        ns.NextLanePackets=function(data,fast) captured_fast=fast; return lanes(data,fast) end
        now=2; tickers[2].callback()
    ''')
    fast = json.loads(lua.eval('ns.EncodeJSON(captured_fast)'))
    assert fast["actionbar_fast"][0][0] == 372608
    assert fast["actionbar_context"]["kind"] == "SKYRIDING"
    assert fast["actionbar_context"]["revision"] == full["skyriding_bar"]["revision"]

    lua.execute('frames[2].OnEvent(frames[2],"UPDATE_BONUS_ACTIONBAR"); now=3; tickers[2].callback()')
    newer = json.loads(lua.eval('ns.EncodeJSON(captured_fast)'))
    assert newer["actionbar_context"]["revision"] > fast["actionbar_context"]["revision"]


def test_vehicle_override_page_takes_priority_over_bonus_skyriding_page():
    lua = _load_main_addon('''
        function GetBonusBarOffset() return 5 end
        C_ActionBar.HasOverrideActionBar=function() return true end
        C_ActionBar.GetOverrideBarIndex=function() return 18 end
        C_ActionBar.GetActionInfo=function(slot)
            if slot==205 then return "spell",305831 end
            if slot==121 then return "spell",372608 end
        end
    ''')
    full = json.loads(lua.eval('ns.EncodeJSON(AIPlayerControllerExportDB.latest)'))
    assert full["actionbar_context"]["kind"] == "OVERRIDE"
    assert full["skyriding_bar"] is False


def test_full_snapshot_does_not_inherit_a_newer_fast_context_for_old_action_rows():
    assembler = PacketAssembler()
    full = snapshot(actionbar_context=NORMAL, actionbar_snapshot_context=NORMAL, skyriding_bar=False)
    result = assembler.feed('AIPC5|sky-test|1|0|1|STATE|' + json.dumps(full), now=1.)
    fast = {"monotonic_time": 2., "actionbar_context": SKY, "movement": {"flying": True}}
    result = assembler.feed('AIPC5|sky-test|2|0|1|FAST|' + json.dumps(fast), now=2.)
    assert "actionbar_snapshot_context" not in result  # FAST is a bounded delta.
    full["monotonic_time"] = 1.5
    result = assembler.feed('AIPC5|sky-test|3|0|1|STATE|' + json.dumps(full), now=2.1)
    assert result["actionbar_snapshot_context"] == NORMAL
    assert result["actionbar_context"] == SKY


def test_bounded_fast_transport_retains_actionbar_context():
    lua = lua_runtime()
    lua.execute('''state={monotonic_time=1,timestamp=1001};
        fast={monotonic_time=2,timestamp=1002,actionbar_context={page=11,kind="SKYRIDING",revision=4},
        actionbar_fast={{372608,true,false,0}},movement={flying=true},
        mouseover={guid=string.rep("g",400),name=string.rep("n",400),tooltip=string.rep("t",2000)}}''')
    packet = lua.eval('ns.NextPacket(state,fast)')
    assert len(packet.encode('utf-8')) <= 1000
    body = json.loads(packet.split('|',6)[6])
    assert body["actionbar_context"] == {"page": 11, "kind": "SKYRIDING", "revision": 4}
