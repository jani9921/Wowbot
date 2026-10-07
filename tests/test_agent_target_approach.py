from test_agent_core import agent, quest_npc_boxes, state
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.visual_approach import VisualApproachController, VisualApproachPhase


def remote_target(t=1, **overrides):
    target = {"guid": "mob-1", "name": "Murloc Spearhunter", "attackable": True, "dead": False,
              "screen_position": {"x": .3, "y": .6, "sample_time": t,
                                  "source": "NAMEPLATE_API", "coordinate_space": "CLIENT_BOTTOM_LEFT"}}
    target.update(overrides)
    return state(t, target=target, active_quests=[{"quest_id": 123, "objectives": [{"description": "Items from defeated Murlocs"}]}],
                 actionbar=[{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1", "is_harmful": True,
                             "is_usable": True, "in_range": False, "cooldown_remaining": 0}])


def test_out_of_range_target_uses_short_moving_arc_not_blind_spell():
    value, exe = agent()
    value.tick(remote_target(), 1)
    assert value.last_decision["skill"] == "VISUAL_APPROACH"
    assert exe.commands[0].binding == "MOVEFORWARD"
    assert exe.commands[0].simultaneous == ("TURNLEFT",)
    assert exe.commands[0].duration <= .15


def test_exact_guid_nameplate_links_selected_target_to_current_unknown_subject_track():
    world = WorldModel()
    payload = state(
        5., target={"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                    "attackable": True, "dead": False, "screen_position": None},
        nameplates=[{"guid": "Creature-Murloc", "name": "Murloc Watershaper",
                     "nx": .56, "ny": .72}],
        visual_candidates=[{
            "source": "WORLD3D", "detector_kind": "unknown_subject_candidate",
            "semantic_type": "UNKNOWN", "track_id": "WORLD3D:47",
            "x": .55, "y": .57, "confidence": .74,
            "bbox_height_fraction": .10,
            "bbox": {"left": 500, "top": 100, "right": 570, "bottom": 260},
            "visual_signature": {"signature_id": "murloc-shape"},
        }])

    assert world.ingest(Observation.create(payload, 5.))
    target = world.state["target"]

    assert target["screen_position"]["source"] == "NAMEPLATE_API"
    assert target["screen_position"]["identity_source"] == "EXACT_GUID_NAMEPLATE"
    assert target["screen_position"]["track_id"] == "WORLD3D:47"
    assert target["visual_track_id"] == "WORLD3D:47"


def test_collect_objective_does_not_blind_tab_before_visual_identity():
    value, executor = agent()
    objective = {"description": "0/6 First Aid Kits recovered from defeated Murlocs",
                 "raw_type": "item", "type": "COLLECT"}
    quest = [{"quest_id": 55122, "objectives": [objective]}]
    value.tick(state(active_quests=quest), 1.)

    assert not (value.pending and value.pending.proposal.skill == "ACQUIRE_TARGET")
    assert not any(command.binding == "TARGETNEARESTENEMY"
                   for command in executor.commands)


def test_combat_remains_available_from_fresh_fast_target_and_actionbar_when_detail_is_old():
    world = WorldModel()
    payload = remote_target(state_age=99)
    payload["target"]["screen_position"] = None
    payload["actionbar"][0]["in_range"] = True
    assert world.ingest(Observation.create(payload, 1.))
    proposal = Proposal.make("COMBAT", "test", {"guid": "mob-1"})
    assert SkillRegistry().available(proposal, world)


def test_target_approach_requires_fresh_identified_visible_target():
    for override in ({"screen_position": None}, {"attackable": False},
                     {"screen_position": {"x": .3, "sample_time": -5, "source": "NAMEPLATE_API", "coordinate_space": "CLIENT_BOTTOM_LEFT"}}):
        value, exe = agent()
        value.tick(remote_target(**override), 1)
        assert value.last_decision["skill"] not in {"APPROACH_TARGET", "VISUAL_APPROACH"}


def test_visual_approach_without_track_uses_each_fresh_selected_target_nameplate_sample():
    controller = VisualApproachController()
    first = remote_target(1)
    intent = {"guid": "mob-1", "purpose": "COMBAT",
              "screen_position": first["target"]["screen_position"]}
    controller.start(intent, first, "vision:1", 1.)

    moved = remote_target(1.2)
    moved["target"]["screen_position"] = {
        **moved["target"]["screen_position"], "x": .72, "sample_time": 1.2}
    controller.observe(moved, "vision:2", 1.2)

    assert controller.samples[-1].x == .72
    assert controller.samples[-1].source == "NAMEPLATE_API"


def test_hostile_mouseover_anchor_drives_one_persistent_approach_until_spell_range():
    value, exe = agent()
    data = remote_target(screen_position=None)
    data["mouseover"] = data["target"]
    data["cursor_position"] = {"nx": .72, "ny": .43}
    data["cursor_sample_time"] = 1
    value.tick(data, 1)
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    action_id = value.pending.action_id
    assert value.pending.proposal.parameters["screen_position"]["source"] == "CONFIRMED_MOUSEOVER_ANCHOR"

    update = remote_target(2, screen_position=None)
    update["mouseover"] = None
    update["position"] = {"x": .501, "y": .499}
    value.tick(update, 2)
    assert value.pending and value.pending.action_id == action_id
    assert value.pending.proposal.skill == "VISUAL_APPROACH"
    assert exe.stops >= 1  # lost visual feedback releases W immediately

    reached = remote_target(3, screen_position=None)
    reached["mouseover"] = None
    reached["actionbar"][0]["in_range"] = True
    value.tick(reached, 3)
    assert value.last_result["skill"] == "VISUAL_APPROACH"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.pending and value.pending.proposal.skill == "COMBAT"


def test_approach_stops_at_range_and_has_per_target_budget():
    value, exe = agent()
    value.approach_counts["mob-1"] = 24
    value.tick(remote_target(), 1)
    assert value.last_decision["reason"] == "target_approach_budget_exhausted"
    assert not exe.commands
    value, exe = agent()
    data = remote_target()
    data["actionbar"][0]["in_range"] = True
    value.tick(data, 1)
    assert value.last_decision["skill"] == "COMBAT"


def test_no_path_charge_rejection_repositions_instead_of_retrying_charge():
    value, exe = agent()
    initial = remote_target()
    initial["actionbar"][0]["in_range"] = True
    value.tick(initial, 1)
    assert value.pending and value.pending.proposal.skill == "COMBAT"
    assert exe.commands[-1].binding == "ACTIONBUTTON1"

    rejected = remote_target(2)
    rejected["actionbar"][0]["in_range"] = True
    rejected["ui_error"] = "No path available"
    value.tick(rejected, 2)

    assert value.last_result["skill"] == "COMBAT"
    assert value.last_result["reason"] == "client_error:No path available"
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    follow = remote_target(2.1)
    follow["actionbar"][0]["in_range"] = True
    follow["ui_error"] = "No path available"
    value.tick(follow, 2.1)
    assert exe.commands[-1].binding in {"MOVEFORWARD", "TURNLEFT", "TURNRIGHT"}


def test_casting_cannot_be_interrupted_by_approach():
    value, exe = agent()
    data = remote_target()
    data["is_casting"] = True
    value.tick(data, 1)
    assert value.last_decision["skill"] == "WAIT" and not exe.commands


def test_friendly_interaction_range_error_keeps_target_and_approaches_without_reinspection():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "attackable": False, "dead": False,
              "world_position": {"x": 110., "y": 100., "z": 3.,
                                  "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    player = {"x": 100., "y": 100., "z": 3., "instance_id": 2175,
              "coordinate_space": "WORLD_YARDS"}
    value.tick(state(1, target=target, mouseover=target, player_world_position=player,
                     world_map_open=False, active_quests=[]), 1)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    interact_action = value.pending.action_id

    value.tick(state(2, target=target, mouseover=target,
                     player_world_position=player, monotonic_time=2,
                     ui_error="You need to be closer to interact with that target.",
                     world_map_open=False, active_quests=[]), 2)

    assert value.autonomy.commitment
    assert value.autonomy.commitment.target_guid == "jaina"
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert value.pending.action_id == interact_action
    request = value.active_skill.state.skill_context["interaction"]["approach_request"]
    assert request["kind"] == "WORLD_ENTITY"
    assert value.navigation.movement_snapshot()["destination"]["coordinate_space"] == "WORLD_YARDS"
    assert value.navigation.movement_snapshot()["destination"]["target_guid"] == "jaina"
    assert exe.commands[-1].binding == "MOVEFORWARD"
    assert all(command.kind != "HOVER" for command in exe.commands)

    # Fresh telemetry updates the same persistent INTERACT-owned reach
    # controller; the Planner cannot emit another movement action or inspect
    # a random screen point between range error and interaction.
    value.tick(state(3, target=target, mouseover=False, monotonic_time=3,
                     player_world_position={**player, "x": 102.},
                     ui_error="You need to be closer to interact with that target.",
                     world_map_open=False, active_quests=[]), 3)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert value.pending.action_id == interact_action
    assert value.autonomy.commitment.target_guid == "jaina"
    assert all(command.kind != "HOVER" for command in exe.commands)

    value.tick(state(4, target=target, mouseover=False, monotonic_time=4,
                     player_world_position={**player, "x": 104.}, ui_error=None,
                     world_map_open=False, active_quests=[]), 4)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert value.pending.action_id == interact_action
    assert value.autonomy.commitment.target_guid == "jaina"

    # Arrival resumes the interact key inside the same bounded attempt.
    value.tick(state(5, target=target, mouseover=False, monotonic_time=5,
                     player_world_position={**player, "x": 106.}, ui_error=None,
                     world_map_open=False, active_quests=[]), 5)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert value.pending.action_id == interact_action
    assert exe.commands[-1].binding == "INTERACTTARGET"


def test_friendly_reach_opens_map_before_db_or_blind_movement_without_coordinates():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "attackable": False, "dead": False}
    value.tick(state(1, target=target, mouseover=target, world_map_open=False), 1)
    value.tick(state(2, target=target,
                     ui_error="You need to be closer to interact with that target.",
                     world_map_open=False), 2)
    assert value.pending and value.pending.proposal.skill == "OPEN_MAP"
    assert value.last_decision["skill"] == "OPEN_MAP"
    assert [command.binding for command in exe.commands] == ["INTERACTTARGET", "TOGGLEWORLDMAP"]
    assert not any(command.kind == "BIND" and command.binding == "MOVEFORWARD" for command in exe.commands)


def test_confirmed_mouseover_anchor_approaches_friendly_before_map_fallback():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC",
              "attackable": False, "dead": False}
    cursor = {"nx": .78, "ny": .52}
    visual = Observation.create({"session_id": "test:player-1", "timestamp": 1,
        "frame_id": "vision:jaina", "visual_candidates": [{
            "source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .78, "y": .52,
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "stable_frames": 4, "confidence": .8, "inspectable": True}]}, 1, "WORLD3D")
    value.tick(state(1, target=target, mouseover=target, cursor_position=cursor,
                     world_map_open=False), 1, (visual,))
    # User direction 2026-09-30: with live World3D the selected friendly unit
    # is approached first while its box is not interaction-sized; no silent
    # far-away INTERACT is spent to discover the range.
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    request = value.pending.proposal.parameters
    assert request["purpose"] == "INTERACT"
    assert request["track_id"] == "WORLD3D:jaina"

    value.tick(state(1.5, target=target, mouseover=False, cursor_position=cursor,
                     world_map_open=False), 1.5)

    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    assert value.autonomy.commitment.target_guid == "jaina"
    # User 2026-10-01: walk continuously.  A moderate screen-space error is
    # steered while the forward lease is kept (one arc); only a target far
    # off-centre (>.35) turns in place.
    assert exe.commands[-1].binding == "MOVEFORWARD"
    assert "TURNRIGHT" in exe.commands[-1].simultaneous
    assert not any(command.binding == "TOGGLEWORLDMAP" for command in exe.commands)


def test_visual_approach_uses_fresh_identity_anchor_before_tracker_catches_up():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    anchor = {"x": .52, "y": .61, "sample_time": 1.,
              "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_id": "WORLD3D:jaina", "track_confidence": .7}
    data = state(1, target=target, visual_candidates=[])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor,
                      "range_block_started_at": 0.}, data, "vision:1", 1.)
    commands = controller.command(data, "vision:1", 1.)
    assert controller.phase == VisualApproachPhase.ADVANCING
    assert commands and commands[0].binding == "MOVEFORWARD"
    assert all(command.kind != "CAMERA_PAN" for command in commands)


def test_selected_committed_guid_suppresses_target_clearing_camera_pan():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    anchor = {"x": .52, "y": .61, "sample_time": 1.,
              "source": "CONFIRMED_MOUSEOVER_ANCHOR", "track_id": "WORLD3D:jaina"}
    data = state(1, target=target, visual_candidates=[])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor},
                     data, "vision:1", 1.)
    stale = state(2, target=target, visual_candidates=[])
    assessment = controller.observe(stale, "vision:2", 2.)
    assert assessment.phase == VisualApproachPhase.OCCLUDED
    assert controller.command(stale, "vision:2", 2.) == ()


def test_visual_approach_moves_before_repeating_interaction_probe():
    controller = VisualApproachController()
    controller.range_probe_enabled = True      # opt-in (AIPC_VA_RANGE_PROBE=1)
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE"}
    data = state(1, target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "range_block_started_at": 0.},
                     data, "vision:1", 1.)
    first = controller.command(data, "vision:1", 1.)
    assert first[0].binding == "MOVEFORWARD"
    controller.observe(state(1.2, target=target, visual_candidates=[track]), "vision:2", 1.2)
    second = controller.command(data, "vision:2", 1.2)
    assert second[0].binding == "MOVEFORWARD"
    for index, at in enumerate((1.4, 1.6, 1.8), start=3):
        controller.observe(state(at, target=target, visual_candidates=[track]),
                           f"vision:{index}", at)
        assert controller.command(data, f"vision:{index}", at)[0].binding == "MOVEFORWARD"
    controller.observe(state(2.3, target=target, visual_candidates=[track]), "vision:6", 2.3)
    assert controller.command(data, "vision:6", 2.3)[0].binding == "INTERACTTARGET"


def test_interact_visual_approach_reconfirms_the_live_track_before_more_forward_motion():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "observed_at": 1.0}
    initial = state(1, target=target, visual_candidates=[track],
                    mouseover=target, mouseover_sample_time=1.,
                    cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.)
    anchor = {"x": .51, "y": .62, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE", "orientation_snapshot": 0.}
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor}, initial, "vision:1", 1.)
    assert controller.command(initial, "vision:1", 1.)[0].binding == "MOVEFORWARD"
    for index, at in enumerate((1.2, 1.4), start=2):
        current = state(at, target=target, visual_candidates=[{**track, "observed_at": at}],
                        mouseover=target, mouseover_sample_time=1.,
                        cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.)
        controller.observe(current, f"vision:{index}", at)
        # User 2026-10-01: no pointer work while approaching.
        assert controller.command(current, f"vision:{index}", at)[0].binding == "MOVEFORWARD"
    in_range = {**track, "bbox_height_fraction": .2}
    probe_state = state(1.6, target=target, visual_candidates=[{**in_range, "observed_at": 1.6}],
                        mouseover=target, mouseover_sample_time=1.,
                        cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.)
    controller.observe(probe_state, "vision:4", 1.6)
    hover = controller.command(probe_state, "vision:4", 1.6)
    assert hover and hover[0].kind == "HOVER"
    # A stale value from before the controller moved its own pointer cannot
    # validate the next advance segment.
    waiting = controller.observe(probe_state, "vision:5", 1.7)
    assert waiting.reason == "awaiting_visual_identity_reconfirmation"
    assert controller.command(probe_state, "vision:5", 1.7) == ()
    confirmed = state(1.8, target=target,
                      visual_candidates=[{**in_range, "observed_at": 1.8}],
                      mouseover=target, mouseover_sample_time=1.8,
                      cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.8)
    controller.observe(confirmed, "vision:6", 1.8)
    assert controller.identity_reconfirmations == 1
    assert controller.observe(confirmed, "vision:7", 1.85).phase == VisualApproachPhase.INTERACTION_READY


def test_interact_visual_approach_proceeds_when_its_arrival_rehover_is_unconfirmed():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "observed_at": 1.0}
    initial = state(1, target=target, visual_candidates=[track])
    anchor = {"x": .51, "y": .62, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE"}
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor}, initial, "vision:1", 1.)
    for index, at in enumerate((1., 1.2, 1.4, 1.6), start=1):
        current = state(at, target=target, visual_candidates=[{
            **track, "observed_at": at, "bbox_height_fraction": .2 if at >= 1.6 else .08}])
        if index > 1:
            controller.observe(current, f"vision:{index}", at)
        controller.command(current, f"vision:{index}", at)
    assert controller.identity_recheck_requested_at is not None
    waiting = controller.observe(
        state(2.6, target=target, visual_candidates=[track]), "vision:6", 2.6)
    assert not waiting.terminal
    assert waiting.reason == "awaiting_visual_identity_reconfirmation"
    # User 2026-10-01: the pointer sliding off the NPC must not abort the
    # approach; in range the selected GUID proceeds to INTERACT.
    late = state(3.7, target=target, visual_candidates=[{**track, "bbox_height_fraction": .2}])
    proceeding = controller.observe(late, "vision:7", 3.7)
    assert not proceeding.terminal
    assert proceeding.reason == "identity_rehover_unconfirmed_proceeding_with_selected_guid"
    assert controller.observe(late, "vision:8", 3.75).phase == VisualApproachPhase.INTERACTION_READY


def test_interact_visual_approach_accepts_live_addon_latency_after_rehover():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "observed_at": 1.0}
    initial = state(1, target=target, visual_candidates=[track],
                    mouseover=target, mouseover_sample_time=1.,
                    cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.)
    anchor = {"x": .51, "y": .62, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE", "orientation_snapshot": 0.}
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor},
                     initial, "vision:1", 1.)
    for index, at in enumerate((1., 1.2, 1.4, 1.6), start=1):
        current = state(at, target=target,
                        visual_candidates=[{**track, "observed_at": at,
                                            "bbox_height_fraction": .2 if at >= 1.6 else .08}],
                        mouseover=target, mouseover_sample_time=1.,
                        cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=1.)
        if index > 1:
            controller.observe(current, f"vision:{index}", at)
        controller.command(current, f"vision:{index}", at)
    assert controller.identity_recheck_requested_at == 1.6

    # The production detail lane answered 1.48 seconds after HOVER.  This is
    # still a fresh, exact GUID confirmation and must resume bounded motion.
    delayed = state(3.08, target=target,
                    visual_candidates=[{**track, "observed_at": 3.08, "bbox_height_fraction": .2}],
                    mouseover=target, mouseover_sample_time=3.08,
                    cursor_position={"nx": .51, "ny": .62}, cursor_sample_time=3.08)
    controller.observe(delayed, "vision:5", 3.08)
    assert controller.identity_reconfirmations == 1
    assert controller.observe(delayed, "vision:6", 3.1).phase == VisualApproachPhase.INTERACTION_READY


def test_selected_interaction_target_rehovers_last_confirmed_point_during_short_track_gap():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "observed_at": 1.0}
    anchor = {"x": .51, "y": .62, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE", "orientation_snapshot": 0.}
    initial = state(1, target=target, visual_candidates=[track], mouseover=target,
                    mouseover_sample_time=1., cursor_position={"nx": .51, "ny": .62},
                    cursor_sample_time=1.)
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT",
                      "screen_position": anchor}, initial, "vision:1", 1.)
    assert controller.last_confirmed_hover_point == {"x": .51, "y": .62, "at": 1.}
    # The target selection remains authoritative while a detector refresh
    # misses the World3D candidate. Re-hover -- never W -- is the first action.
    # A camera/player heading change invalidates the old frozen anchor, so
    # only a fresh re-hover may safely reacquire the selected target.
    gap = state(1.2, target=target, visual_candidates=[], orientation=.2)
    assessment = controller.observe(gap, "vision:2", 1.2)
    assert assessment.phase == VisualApproachPhase.OCCLUDED
    command = controller.command(gap, "vision:2", 1.2)
    assert command and command[0].kind == "HOVER"
    assert (command[0].x, command[0].y) == (.51, .62)


def test_visual_approach_never_refreshes_forward_from_frozen_visual_sample():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "observed_at": 1.0}
    data = state(1, target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT"}, data, "vision:1", 1.)
    assert controller.command(data, "vision:1", 1.)[0].binding == "MOVEFORWARD"
    # New addon FAST_STATE identity, but the same visual projection.
    controller.observe(state(1.1, target=target, visual_candidates=[track]),
                       "vision:1:fast:2", 1.1)
    assert controller.command(data, "vision:1:fast:2", 1.1) == ()


def test_pending_visual_approach_does_not_cancel_lease_on_duplicate_telemetry():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC",
              "attackable": False, "dead": False}
    cursor = {"nx": .51, "ny": .62}
    visual = Observation.create({"session_id": "test:player-1", "timestamp": 1,
        "frame_id": "vision:jaina", "visual_candidates": [{
            "source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .51, "y": .62,
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "stable_frames": 4, "confidence": .8, "inspectable": True,
            "observed_at": 1.}]}, 1, "WORLD3D")
    value.tick(state(1, target=target, mouseover=target, cursor_position=cursor,
                     world_map_open=False), 1, (visual,))
    visual_update = Observation.create({"session_id": "test:player-1", "timestamp": 1.5,
        "frame_id": "vision:jaina:2", "visual_candidates": [{
            "source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .51, "y": .62,
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "stable_frames": 5, "confidence": .8, "inspectable": True,
            "observed_at": 1.5}]}, 1.5, "WORLD3D")
    value.tick(state(1.5, target=target, mouseover=False, cursor_position=cursor,
                     world_map_open=False), 1.5, (visual_update,))
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    stops_after_forward = exe.stops
    value.tick(state(1.6, target=target, mouseover=False, cursor_position=cursor,
                     world_map_open=False), 1.6)
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    assert exe.stops == stops_after_forward


def test_duplicate_fast_telemetry_does_not_count_as_visual_no_progress():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE",
             "bbox_height_fraction": .09, "observed_at": 1.0}
    data = state(1, target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT"}, data, "vision:1", 1.)
    for index in range(2, 12):
        controller.observe(state(1 + index/100, target=target,
                                 visual_candidates=[track]),
                           f"vision:1:fast:{index}", 1 + index/100)
    assert controller.visual_no_progress_samples == 0


def test_interact_waits_for_delayed_retail_range_error_without_opening_map():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC",
              "attackable": False, "dead": False}
    cursor = {"nx": .53, "ny": .66}
    value.tick(state(1, target=target, mouseover=target, cursor_position=cursor,
                     world_map_open=False), 1)
    assert value.pending and value.pending.proposal.skill == "INTERACT"

    # The live exporter delivered this result more than five seconds after
    # INTERACT. The interaction must still own the subgoal at four seconds.
    value.tick(state(5, target=target, mouseover=target, cursor_position=cursor,
                     world_map_open=False), 5)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert not any(command.binding == "TOGGLEWORLDMAP" for command in exe.commands)

    value.tick(state(6.5, target=target, mouseover=target, cursor_position=cursor,
                     ui_error="You need to be closer to interact with that target.",
                     world_map_open=False), 6.5)
    assert value.pending and value.pending.proposal.skill == "INTERACT"
    assert value.active_skill.state.skill_context["interaction"]["approach_request"]["purpose"] == "INTERACT"
    assert value.autonomy.commitment.target_guid == "jaina"
    assert not any(command.binding == "TOGGLEWORLDMAP" for command in exe.commands)


def test_world_map_is_closed_before_committed_visual_approach():
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC",
              "attackable": False, "dead": False}
    value.planner.quest.interaction_range_blocks["jaina"] = {
        "started_at": 1., "belief": "SUPPORTED", "source": "CLIENT_ERROR"}
    from wowbot.agent.autonomy_loop import CommittedSubgoal
    value.autonomy.commitment = CommittedSubgoal(
        "commit-jaina", value.goal.goal_id, "target:jaina", "TARGET",
        "jaina", "npc:156626", (), "INTERACT", 0., 0., session_id="test:player-1",
        map_id=1609)
    value.world.session_id = "test:player-1"
    value.world.set_runtime_context(goal=value.goal,
                                    commitment=value.autonomy.commitment)
    value.tick(state(1, target=target, mouseover=target,
                     cursor_position={"nx": .53, "ny": .66},
                     ui_error="You need to be closer to interact with that target.",
                     world_map_open=True), 1)
    assert value.pending and value.pending.proposal.skill == "CLOSE_MAP"
    assert exe.commands[-1].binding == "TOGGLEWORLDMAP"


def test_target_click_waits_for_retail_export_latency_before_map_search():
    value, exe = agent()
    mouse = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
             "npc_id": 156626, "unit_type": "NPC",
             "attackable": False, "dead": False}
    cursor = {"nx": .78, "ny": .52}
    value.tick(state(1, target=None, mouseover=mouse, cursor_position=cursor,
                     world_map_open=False, visual_candidates=quest_npc_boxes(.78, .52)), 1)
    assert value.pending and value.pending.proposal.skill == "TARGET"

    # Live AIPC5/debug runs have delivered the authoritative target projection
    # after more than five seconds.  The confirmed identity must remain
    # committed while Retail/addon target telemetry is still catching up.
    value.tick(state(6.2, target=None, mouseover=mouse, cursor_position=cursor,
                     world_map_open=False), 6.2)
    assert value.pending and value.pending.proposal.skill == "TARGET"
    assert value.autonomy.commitment.target_guid == "jaina"
    assert not any(command.binding == "TOGGLEWORLDMAP" for command in exe.commands)

    value.tick(state(7.8, target=mouse, mouseover=mouse, cursor_position=cursor,
                     world_map_open=False), 7.8)
    assert value.last_result["skill"] == "TARGET"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.autonomy.commitment.target_guid == "jaina"
    assert value.last_decision["skill"] == "INTERACT"


def test_self_player_mouseover_is_never_promoted_to_npc_target_or_interaction():
    value, exe = agent()
    own_guid = "Player-1402-SELF"
    own = {"guid": own_guid, "name": "Own Character", "unit_type": "PLAYER",
           "is_player": True, "attackable": False, "dead": False}
    value.tick(state(1, character_guid=own_guid, target=None, mouseover=own,
                     cursor_position={"nx": .5, "ny": .55}, world_map_open=False), 1)
    assert value.last_decision["skill"] != "TARGET"

    value, exe = agent()
    value.tick(state(1, character_guid=own_guid, target=own, mouseover=own,
                     cursor_position={"nx": .5, "ny": .55}, world_map_open=False), 1)
    assert value.last_decision["skill"] not in {"TARGET", "INTERACT", "TALK", "APPROACH_TARGET", "VISUAL_APPROACH"}
    assert not any(command.binding == "INTERACTTARGET" for command in exe.commands)


def test_fresh_fast_mouseover_can_target_when_full_snapshot_is_old():
    """The mouseover lane and paged full-state lane have independent ages."""
    value, _ = agent()
    mouse = {"guid": "Creature-0-3109-2175-145635-156626-000022EF4C",
             "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False,
             "identity_source": "WOW_API_MOUSEOVER"}
    # World3D boxes arrive on their own perception lane, never in FAST:
    # Jaina's box with the "!" over it (no active quest: quest NPCs only).
    value.world.session_id = "test:player-1"
    value.world.ingest(Observation.create({
        "session_id": "test:player-1", "timestamp": 10, "frame_id": "vision:10",
        "visual_candidates": quest_npc_boxes(.5792, .5889)}, 10, "WORLD3D"))
    value.tick(state(10, target=None, mouseover=mouse,
                     cursor_position={"nx": .5792, "ny": .5889},
                     cursor_sample_time=10, mouseover_sample_time=10,
                     state_age=3, transport_kind="FAST",
                     telemetry_lane="FAST_STATE"), 10)
    assert value.pending and value.pending.proposal.skill == "TARGET"
    assert value.pending.proposal.parameters["guid"] == mouse["guid"]


def test_target_handoff_refuses_stale_or_displaced_cursor_even_when_guid_survives():
    """GUID evidence survives, but an old screen anchor is never clickable."""
    mouse = {"guid": "Creature-0-0-0-0-156626-0000000001",
             "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    registry = SkillRegistry()
    proposal = Proposal.make("TARGET", "fresh hover target", {
        "x": .5792, "y": .5889, "guid": mouse["guid"],
        "ground_truth_handoff": True})

    model = WorldModel()
    # Same GUID, but camera/cursor movement happened before dispatch: no click.
    model.ingest(Observation.create(state(10, target=None, mouseover=mouse,
                                         cursor_position={"nx": .61, "ny": .5889},
                                         cursor_sample_time=10, mouseover_sample_time=10), 10))
    assert registry.available(proposal, model) is False

    # Back at the original pixel, but the fast edge is over 350 ms old: still
    # no click. Reinspection must produce a current co-sampled observation.
    model.ingest(Observation.create(state(11, target=None, mouseover=mouse,
                                         cursor_position={"nx": .5792, "ny": .5889},
                                         cursor_sample_time=10.6, mouseover_sample_time=10.6), 11))
    assert registry.available(proposal, model) is False


def test_mouseover_anchor_uses_bottom_left_coordinates_and_expires_after_movement():
    model = WorldModel()
    mouse = {"guid": "jaina", "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    first = state(1, mouseover=mouse, cursor_position={"nx": .53, "ny": .66},
                  cursor_sample_time=1, mouseover_sample_time=1,
                  player_world_position={"x": 0., "y": 0., "instance_id": 2175})
    model.ingest(Observation.create(first, 1))
    anchor = model.state["confirmed_mouseover_anchors"]["jaina"]
    assert anchor["y"] == .66

    moved = state(2, mouseover=None, cursor_position={"nx": .53, "ny": .66},
                  cursor_sample_time=2, mouseover_sample_time=2,
                  player_world_position={"x": 1., "y": 0., "instance_id": 2175})
    model.ingest(Observation.create(moved, 2))
    assert "jaina" not in model.state["confirmed_mouseover_anchors"]


def test_quest_mouseover_semantics_survive_movement_without_reusing_screen_anchor():
    model = WorldModel()
    guid = "Creature-0-0-0-0-154168-0000000001"
    quest = {"quest_id": 55174, "is_complete": False,
             "objectives": [{"description": "Raw Meat collected", "current": 0}]}
    mouse = {"guid": guid, "name": "Prickly Porcupine", "npc_id": 154168,
             "unit_type": "NPC", "is_attackable": True, "is_dead": False,
             "quest_related": True, "quest_id": 55174}
    first = state(1, target=mouse, mouseover=mouse, active_quests=[quest],
                  cursor_position={"nx": .53, "ny": .66},
                  cursor_sample_time=1, mouseover_sample_time=1,
                  player_world_position={"x": 0., "y": 0., "instance_id": 2175})
    model.ingest(Observation.create(first, 1))

    selected = {key: value for key, value in mouse.items()
                if key not in {"quest_related", "quest_id"}}
    moved = state(2, target=selected, mouseover=None, active_quests=[quest],
                  cursor_position={"nx": .75, "ny": .55},
                  cursor_sample_time=2, mouseover_sample_time=2,
                  player_world_position={"x": 1., "y": 0., "instance_id": 2175},
                  actionbar=[{"id": 1, "kind": "spell", "action": "ACTIONBUTTON1",
                              "is_harmful": True, "is_usable": True, "in_range": True,
                              "cooldown_remaining": 0}])
    model.ingest(Observation.create(moved, 2))

    assert guid not in model.state["confirmed_mouseover_anchors"]
    assert model.state["target"]["quest_relevant"] is True
    assert model.state["target"]["quest_id"] == 55174
    assert "screen_position" not in model.state["target"]
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), model, 2)
    combat = next(proposal for proposal in proposals if proposal.skill == "COMBAT")
    assert combat.parameters["guid"] == guid
    assert 55174 in combat.parameters["quest_ids"]


def test_quest_mouseover_semantics_expire_when_quest_is_no_longer_active():
    model = WorldModel()
    guid = "Creature-0-0-0-0-154168-0000000001"
    mouse = {"guid": guid, "name": "Prickly Porcupine", "npc_id": 154168,
             "unit_type": "NPC", "is_attackable": True, "is_dead": False,
             "quest_related": True, "quest_id": 55174}
    first = state(1, target=mouse, mouseover=mouse,
                  active_quests=[{"quest_id": 55174, "is_complete": False}],
                  cursor_position={"nx": .53, "ny": .66},
                  cursor_sample_time=1, mouseover_sample_time=1)
    model.ingest(Observation.create(first, 1))

    selected = {key: value for key, value in mouse.items()
                if key not in {"quest_related", "quest_id"}}
    model.ingest(Observation.create(state(
        2, target=selected, mouseover=None, active_quests=[],
        cursor_sample_time=2, mouseover_sample_time=2), 2))

    assert guid not in model.state["confirmed_entity_semantics"]
    assert model.state["target"].get("quest_relevant") is not True


def test_mouseover_anchor_expires_after_camera_motion_without_player_turn():
    model = WorldModel()
    model.ingest(Observation.create(state(1, mouseover=None), 1))
    model.ingest(Observation.create({
        "session_id": "test:player-1", "timestamp": 1.1, "frame_id": "camera:1",
        "camera_state": {"yaw_estimate": 0., "pitch_estimate": 0.},
    }, 1.1, "CAMERA_CONTROL"))
    mouse = {"guid": "jaina", "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    model.ingest(Observation.create(state(
        2, mouseover=mouse, cursor_position={"nx": .53, "ny": .66},
        cursor_sample_time=2, mouseover_sample_time=2, orientation=0.), 2))
    assert model.state["confirmed_mouseover_anchors"]["jaina"]["camera_yaw_snapshot"] == 0.

    model.ingest(Observation.create({
        "session_id": "test:player-1", "timestamp": 2.1, "frame_id": "camera:2",
        "camera_state": {"yaw_estimate": 20., "pitch_estimate": 0.},
    }, 2.1, "CAMERA_CONTROL"))
    assert "jaina" not in model.state["confirmed_mouseover_anchors"]


def test_late_world3d_projection_binds_confirmed_mouseover_identity_to_track():
    model = WorldModel()
    mouse = {"guid": "jaina", "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    addon = state(1, mouseover=mouse, cursor_position={"nx": .53, "ny": .66},
                  cursor_sample_time=1, mouseover_sample_time=1)
    model.ingest(Observation.create(addon, 1))
    visual = Observation.create({"session_id": addon["session_id"], "timestamp": 1.1,
        "frame_id": "vision:1", "visual_candidates": [{
            "source": "WORLD3D", "track_id": "WORLD3D:jaina-subject",
            "detector_kind": "unknown_subject_candidate", "x": .532, "y": .658,
            "stable_frames": 4, "confidence": .8, "inspectable": True}]}, 1.1, "WORLD3D")
    model.ingest(visual)
    anchor = model.state["confirmed_mouseover_anchors"]["jaina"]
    assert anchor["track_id"] == "WORLD3D:jaina-subject"
    assert model.latest_visual_observation_id == visual.observation_id


def test_tdb_reference_reach_stops_when_live_matching_identity_is_seen():
    value, exe = agent()
    value.planner.map_search_exhausted = True
    value.planner.map_search_context = ("test:player-1", 1409, None)
    reference = {"source": "TDB_REFERENCE", "source_sha256": "digest",
        "world_map_id": 2175, "x": 20., "y": 0., "z": 0.,
        "distance_yards": 20., "coordinate_space": "WORLD_YARDS",
        "spawn_ids": [2, 1], "npc_ids": [156626, 166782],
        "quest_ids": [54951], "role_hypothesis": "QUEST_STARTER",
        "identity_confirmed": False}
    base = state(1, map_id=1409, world_map_open=False,
                 player_world_position={"x": 0., "y": 0., "z": 0., "instance_id": 2175},
                 quest_role_reference_candidates=[reference])
    value.tick(base, 1)
    assert value.pending and value.pending.proposal.skill == "REACH_LOCATION"

    mouse = {"guid": "jaina", "name": "Lady Jaina Proudmoore", "npc_id": 156626,
             "unit_type": "NPC", "is_attackable": False, "is_dead": False}
    seen = state(2, map_id=1409, world_map_open=False, mouseover=mouse,
                 cursor_position={"nx": .53, "ny": .66}, cursor_sample_time=2,
                 mouseover_sample_time=2,
                 player_world_position={"x": 1., "y": 0., "z": 0., "instance_id": 2175},
                 quest_role_reference_candidates=[reference],
                 visual_candidates=quest_npc_boxes(.53, .66))
    value.tick(seen, 2)
    # The short-lived live identity must be consumed immediately instead of
    # waiting for the next paged addon sample (when the cursor may no longer be
    # over the NPC).
    assert value.pending and value.pending.proposal.skill == "TARGET"
    assert value.pending.proposal.parameters["guid"] == "jaina"
    assert value.last_result["outcome"] == "SUCCESS"
    assert value.last_result["reason"] == "live_reference_identity_observed"


def test_interaction_sized_friendly_unit_is_interacted_with_directly():
    value, _ = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC",
              "attackable": False, "dead": False}
    cursor = {"nx": .5, "ny": .55}
    visual = Observation.create({"session_id": "test:player-1", "timestamp": 1,
        "frame_id": "vision:jaina", "visual_candidates": [{
            "source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .5, "y": .55,
            "detector_kind": "unknown_subject_candidate", "semantic_type": "UNKNOWN",
            "stable_frames": 6, "confidence": .8, "inspectable": True,
            "bbox_height_fraction": .22}]}, 1, "WORLD3D")
    value.tick(state(1, target=target, mouseover=target, cursor_position=cursor,
                     world_map_open=False), 1, (visual,))
    assert value.pending and value.pending.proposal.skill == "INTERACT"


def test_visual_approach_holds_forward_continuously_without_range_clicks():
    """User 2026-10-01: "not stop-and-go, continuous until it gets there".
    Every INTERACTTARGET range probe released the forward lease."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina",
             "x": .51, "y": .62, "confidence": .8, "lifecycle": "ACTIVE"}
    data = state(1, target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "range_block_started_at": 0.},
                     data, "vision:1", 1.)
    bindings = []
    for index in range(1, 16):
        at = 1. + index*.1
        controller.observe(state(at, target=target, visual_candidates=[track]),
                           f"vision:{index}", at)
        bindings.extend(c.binding for c in controller.command(data, f"vision:{index}", at))
    assert bindings and set(bindings) == {"MOVEFORWARD"}


def test_candidate_association_is_not_rehovered_while_still_approaching():
    """User 2026-10-01: approach without the pointer on the NPC and re-hover
    only once close.  Live 17:25 had 2-4 mid-approach re-hovers, each
    releasing W, and a late addon sample failed the attempt."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .51, "y": .62,
             "confidence": .8, "lifecycle": "ACTIVE", "observed_at": 1.0,
             "bbox_height_fraction": .08}
    anchor = {"x": .51, "y": .62, "source": "CONFIRMED_MOUSEOVER_ANCHOR",
              "track_association": "CANDIDATE", "orientation_snapshot": 0.}
    first = state(1., target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                      "purpose": "INTERACT", "screen_position": anchor}, first, "vision:1", 1.)
    kinds = [c.kind for c in controller.command(first, "vision:1", 1.)]
    for index in range(2, 20):
        t = 1. + index*.1
        current = state(t, target=target, visual_candidates=[{**track, "observed_at": t}])
        controller.observe(current, f"vision:{index}", t)
        kinds.extend(c.binding or c.kind for c in controller.command(current, f"vision:{index}", t))
    assert kinds and "HOVER" not in kinds and controller.identity_rechecks == 0


def test_interact_arrival_stops_then_faces_the_npc_and_leads_the_stop():
    """The arc approach rarely arrives dead-centre; a centred-only arrival
    rule kept W held past the NPC (live 2026-10-01).  In range, the character
    stops and turns to face the NPC before interacting (user 2026-10-01)."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}

    def track(t, height, x):
        return {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": x, "y": .6,
                "confidence": .8, "lifecycle": "ACTIVE", "observed_at": t,
                "bbox_height_fraction": height}

    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT",
                      "ready_bbox_height": .186},
                     state(1., target=target, visual_candidates=[track(1., .15, .62)]),
                     "vision:1", 1.)
    result = None
    for index, (t, height) in enumerate(((1.1, .16), (1.2, .172), (1.3, .181)), start=2):
        current = state(t, target=target, visual_candidates=[track(t, height, .62)])
        result = controller.observe(current, f"vision:{index}", t)
    # In range (lead-time stop) but 12 % off-centre: stop and face the NPC.
    assert result.reason == "in_range_turning_to_face_target"
    turn = controller.command(current, "vision:4", 1.3)
    assert turn and turn[0].binding == "TURNRIGHT" and not turn[0].simultaneous
    facing = state(1.4, target=target, visual_candidates=[track(1.4, .19, .52)])
    result = controller.observe(facing, "vision:5", 1.4)
    assert result.phase == VisualApproachPhase.INTERACTION_READY


def test_pointer_is_kept_on_the_target_without_stopping_the_approach():
    """User 2026-10-01: turning slides the pointer off the NPC; put it back
    while walking (POINTER), never interrupting the approach."""
    from wowbot.skills.visual_runtime import VisualRuntimeRunner

    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .51, "y": .62,
             "confidence": .8, "lifecycle": "ACTIVE", "observed_at": 1.}
    off = {"nx": .2, "ny": .3}
    first = state(1., target=target, visual_candidates=[track], cursor_position=off)
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT"},
                     first, "vision:1", 1.)
    assert controller.command(first, "vision:1", 1.)[0].binding == "MOVEFORWARD"
    second = state(1.1, target=target, visual_candidates=[{**track, "observed_at": 1.1}],
                   cursor_position=off)
    controller.observe(second, "vision:2", 1.1)
    pointer = controller.command(second, "vision:2", 1.1)
    assert pointer[0].kind == "POINTER" and (pointer[0].x, pointer[0].y) == (.51, .62)
    third = state(1.2, target=target, visual_candidates=[{**track, "observed_at": 1.2}],
                  cursor_position={"nx": .51, "ny": .62})
    controller.observe(third, "vision:3", 1.2)
    assert controller.command(third, "vision:3", 1.2)[0].binding == "MOVEFORWARD"

    class Skill:
        def observe(self, *args):
            from wowbot.runtime import SkillResult, SkillStatus
            return SkillResult(SkillStatus.RUNNING, commands=pointer)
        def phase(self, *args):
            return "ADVANCING"
        def snapshot(self, *args):
            return {}

    step = VisualRuntimeRunner(None, Skill()).step_approach(None, {}, "o", 1.)
    assert step.movement_lane is False and step.stop_movement is False


def test_forward_lease_is_kept_through_a_short_gap_between_visual_samples():
    """Live 2026-10-01 17:55: the target's sample did not change for a while
    and W was released after .45 s (stop-and-go).  A still fresh sample may
    re-lease W every .25 s; a stale one never does."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .51, "y": .62,
             "confidence": .8, "lifecycle": "ACTIVE", "observed_at": 1.}
    data = state(1., target=target, visual_candidates=[track])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT"},
                     data, "vision:1", 1.)
    assert controller.command(data, "vision:1", 1.)[0].binding == "MOVEFORWARD"
    assert controller.command(data, "vision:1", 1.1) == ()          # too soon
    assert controller.command(data, "vision:1", 1.3)[0].binding == "MOVEFORWARD"
    assert controller.command(data, "vision:1", 1.6) == ()          # sample now stale


def _edge_track(t, left, top, right, bottom, **extra):
    return {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "confidence": .8,
            "lifecycle": "ACTIVE", "observed_at": t, "x": (left+right)/2/843,
            "y": 1-(top+bottom)/2/475, "bbox_width_fraction": (right-left)/843,
            "bbox_height_fraction": (bottom-top)/475,
            "bbox": {"left": left, "top": top, "right": right, "bottom": bottom}, **extra}


def test_box_lost_through_the_bottom_edge_backs_up_instead_of_running_on():
    """User 2026-10-01: a box leaving the image at the bottom means the
    character ran past the unit; correct by stepping back."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    first = state(1., target=target, visual_candidates=[_edge_track(1., 380, 300, 440, 466)])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "IDENTIFY"},
                     first, "vision:1", 1.)
    controller.observe(first, "vision:1", 1.)
    lost = state(1.3, target=target, visual_candidates=[])
    for index, t in enumerate((1.2, 1.3, 1.4, 1.5), start=2):
        controller.observe(state(t, target=target, visual_candidates=[]), f"vision:{index}", t)
    commands = controller.command(lost, "vision:5", 1.5)
    assert commands and commands[0].binding == "MOVEBACKWARD"


def test_box_lost_through_the_right_edge_turns_right():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    first = state(1., target=target, visual_candidates=[_edge_track(1., 800, 150, 842, 260)])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "IDENTIFY"},
                     first, "vision:1", 1.)
    controller.observe(first, "vision:1", 1.)
    for index, t in enumerate((1.2, 1.3, 1.4, 1.5), start=2):
        controller.observe(state(t, target=target, visual_candidates=[]), f"vision:{index}", t)
    commands = controller.command(state(1.5, target=target, visual_candidates=[]), "vision:5", 1.5)
    assert commands and commands[0].binding == "TURNRIGHT"


def test_box_reaching_the_bottom_of_the_screen_counts_as_arrival():
    """A unit whose box touches the screen bottom is right in front: stop
    instead of holding W into it, whatever the learned height says."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    close = state(1., target=target, visual_candidates=[_edge_track(1., 400, 330, 440, 470)])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT",
                      "ready_bbox_height": .6}, close, "vision:1", 1.)
    result = controller.observe(close, "vision:2", 1.05)
    assert result.phase == VisualApproachPhase.INTERACTION_READY


def test_box_lost_through_the_left_edge_turns_left():
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    first = state(1., target=target, visual_candidates=[_edge_track(1., 1, 150, 42, 260)])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "IDENTIFY"},
                     first, "vision:1", 1.)
    controller.observe(first, "vision:1", 1.)
    for index, t in enumerate((1.2, 1.3, 1.4, 1.5), start=2):
        controller.observe(state(t, target=target, visual_candidates=[]), f"vision:{index}", t)
    commands = controller.command(state(1.5, target=target, visual_candidates=[]), "vision:5", 1.5)
    assert commands and commands[0].binding == "TURNLEFT"


def test_unit_standing_beside_the_own_avatar_counts_as_arrival():
    """User 2026-10-01: arrived when the NPC box is next to / overlaps the own
    avatar box by ~1/4-1/3.  A small distant NPC visually overlapping the
    avatar (it stands behind it) must not count."""
    target = {"guid": "jaina", "attackable": False, "dead": False}
    avatar = {**_edge_track(1., 395, 225, 448, 370), "track_id": "WORLD3D:5",
              "appearance": {"screen_anchored": True}}

    def run(npc_box):
        controller = VisualApproachController()
        npc = _edge_track(1., *npc_box)
        data = state(1., target=target, visual_candidates=[avatar, npc])
        controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "INTERACT",
                          "ready_bbox_height": .6}, data, "vision:1", 1.)
        return controller.observe(data, "vision:2", 1.05)

    beside = run((430, 235, 485, 365))           # similar size, overlapping ~1/3
    assert beside.phase == VisualApproachPhase.INTERACTION_READY or \
        beside.reason == "in_range_turning_to_face_target"
    behind = run((405, 200, 425, 245))           # far behind the avatar, small
    assert behind.phase != VisualApproachPhase.INTERACTION_READY
    assert behind.reason != "in_range_turning_to_face_target"


def test_every_servo_movement_command_is_a_valid_executor_lease():
    """Live 2026-10-01 18:07: a .03 s face-align turn was rejected by the
    executor ("Érvénytelen movement lease") and failed every approach with
    executor_failure, leaving the agent in WAIT next to Jaina."""
    movement = {"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT",
                "STRAFELEFT", "STRAFERIGHT"}
    target = {"guid": "jaina", "attackable": False, "dead": False}
    for offset in [i/100 for i in range(-45, 46, 3)]:
        for height in (.08, .3):                      # approaching, then in range
            controller = VisualApproachController()
            track = {"source": "WORLD3D", "track_id": "WORLD3D:jaina", "x": .5+offset,
                     "y": .6, "confidence": .8, "lifecycle": "ACTIVE", "observed_at": 1.,
                     "bbox_height_fraction": height}
            data = state(1., target=target, visual_candidates=[track])
            controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina",
                              "purpose": "INTERACT"}, data, "vision:1", 1.)
            for index in range(1, 6):
                t = 1. + index*.1
                current = state(t, target=target, visual_candidates=[{**track, "observed_at": t}])
                controller.observe(current, f"vision:{index}", t)
                for command in controller.command(current, f"vision:{index}", t):
                    if command.kind == "BIND" and command.binding in movement:
                        assert .04 <= command.duration <= .35, (offset, height, command)
                        assert all(extra in movement for extra in command.simultaneous)


def test_pointer_mouseover_naming_another_unit_drops_that_track():
    """Live 2026-10-01 18:07: steering followed a gnome player beside Jaina.
    The pointer kept on the followed box makes the addon name the unit under
    it; another GUID there means the track is not the selected unit."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    track = {"source": "WORLD3D", "track_id": "WORLD3D:gnome", "x": .55, "y": .6,
             "confidence": .8, "lifecycle": "ACTIVE", "observed_at": 1.}
    off = {"nx": .2, "ny": .3}
    first = state(1., target=target, visual_candidates=[track], cursor_position=off)
    controller.start({"guid": "jaina", "track_id": "WORLD3D:gnome", "purpose": "INTERACT"},
                     first, "vision:1", 1.)
    controller.command(first, "vision:1", 1.)
    second = state(1.1, target=target, visual_candidates=[{**track, "observed_at": 1.1}],
                   cursor_position=off)
    controller.observe(second, "vision:2", 1.1)
    assert controller.command(second, "vision:2", 1.1)[0].kind == "POINTER"
    gnome = {"guid": "Player-1-ABC", "name": "Gnome", "is_player": True}
    answered = state(1.3, target=target, visual_candidates=[{**track, "observed_at": 1.3}],
                     cursor_position={"nx": .55, "ny": .6}, cursor_sample_time=1.3,
                     mouseover=gnome, mouseover_sample_time=1.3)
    result = controller.observe(answered, "vision:3", 1.3)
    assert result.reason == "pointer_identity_names_another_unit"
    assert "WORLD3D:gnome" in controller.rejected_reacquire_track_ids


def test_unit_vanishing_at_the_own_avatar_backs_up_and_is_not_dropped_early():
    """Live 2026-10-01 18:15: the character ran through Jaina; her box
    vanished at the avatar (not at a screen edge), no correction ran and the
    approach failed after ~0.8 s of misses, leaving REACH_OBJECT/WAIT."""
    controller = VisualApproachController()
    target = {"guid": "jaina", "attackable": False, "dead": False}
    avatar = {**_edge_track(1., 395, 225, 448, 370), "track_id": "WORLD3D:5",
              "appearance": {"screen_anchored": True}}
    npc = _edge_track(1., 400, 250, 450, 365)          # big, overlapping the avatar
    first = state(1., target=target, visual_candidates=[avatar, npc])
    controller.start({"guid": "jaina", "track_id": "WORLD3D:jaina", "purpose": "IDENTIFY"},
                     first, "vision:1", 1.)
    controller.observe(first, "vision:1", 1.)
    commands, failed = [], False
    for index in range(2, 40):                          # ~1.3 s of misses at 30 Hz
        t = 1. + index/30
        current = state(t, target=target, visual_candidates=[avatar])
        result = controller.observe(current, f"vision:{index}", t)
        failed = failed or (result.terminal and not result.success)
        commands.extend(c.binding for c in controller.command(current, f"vision:{index}", t))
    assert "MOVEBACKWARD" in commands
    assert not failed


def test_range_blocked_friendly_approaches_its_live_world3d_track():
    """Issue #94: the WORLD3D_TARGET_TRACK fallback anchor had no
    coordinate_space, so skill availability always rejected the approach."""
    value, exe = agent()
    target = {"guid": "jaina", "name": "Lady Jaina Proudmoore",
              "npc_id": 156626, "unit_type": "NPC", "attackable": False,
              "dead": False, "visual_track_id": "WORLD3D:7"}
    value.planner.quest.interaction_range_blocks["jaina"] = {
        "started_at": 1., "belief": "SUPPORTED", "source": "CLIENT_ERROR"}
    from wowbot.agent.autonomy_loop import CommittedSubgoal
    value.autonomy.commitment = CommittedSubgoal(
        "commit-jaina", value.goal.goal_id, "target:jaina", "TARGET",
        "jaina", "npc:156626", (), "INTERACT", 0., 0., session_id="test:player-1",
        map_id=1609)
    value.world.session_id = "test:player-1"
    value.world.set_runtime_context(goal=value.goal, commitment=value.autonomy.commitment)
    track = {"source": "WORLD3D", "kind": "unknown_subject_candidate", "track_id": "WORLD3D:7",
             "x": .55, "y": .6, "stable_frames": 5, "confidence": .8, "lifecycle": "ACTIVE"}
    value.tick(state(2, target=target, mouseover=None, cursor_position={"nx": .2, "ny": .2},
                     world_map_open=False, visual_candidates=[track]), 2)
    assert value.pending and value.pending.proposal.skill == "VISUAL_APPROACH"
    screen = value.pending.proposal.parameters["screen_position"]
    assert screen["source"] == "WORLD3D_TARGET_TRACK"
    assert screen["coordinate_space"] == "CLIENT_BOTTOM_LEFT"


def test_stale_active_box_is_neither_a_live_track_nor_in_range():
    """Issue #106: an ACTIVE-labelled box last seen 100 s ago was accepted as
    the selected friendly's live track and as visually in range."""
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    quest = Planner(SkillRegistry()).quest
    target = {"guid": "G", "visual_track_id": "WORLD3D:1", "attackable": False}
    box = {"source": "WORLD3D", "track_id": "WORLD3D:1", "lifecycle": "ACTIVE",
           "x": .5, "y": .5, "bbox_height_fraction": .20, "observed_at": 1., "last_seen": 1.}
    stale = {"monotonic_time": 101., "target": target, "visual_candidates": [box]}
    assert quest._target_live_track(stale, "G", target) is None
    assert quest._target_visually_in_range(stale, "G") is False
    fresh = {**stale, "monotonic_time": 2.}            # e.g. reacquired after a camera turn
    assert quest._target_live_track(fresh, "G", target) is box
    assert quest._target_visually_in_range(fresh, "G") is True
