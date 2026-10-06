"""SkillRegistry.commands(): the client commands a proposal sends.

Split out of skills.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import math
from .models import Command, Proposal, number
from .world import WorldModel
from .obstacle_perception import obstacle_bearing
from .skill_contracts import _world_map_open


class SkillCommandsMixin:
    """Methods of SkillRegistry (skills.py); moved verbatim."""

    def commands(self, proposal: Proposal, world: WorldModel) -> tuple[Command, ...]:
        name, params = proposal.skill, proposal.parameters
        # A dialog action is not a generic screen click.  Its preconditions
        # and result verification belong to QuestDialogSkill, dispatched via
        # M0SkillDispatcher.  This fail-closed guard prevents an un-migrated
        # caller from bypassing the normalized action and quest-id checks.
        if name in {"QUEST_DIALOG", "FIELD_TURN_IN", "EXTRA_ACTION", "OBJECT_USE", "USE", "USE_ON_TARGET", "ASSIST", "FOLLOW_INSTRUCTION"}:
            raise ValueError(f"{name} must be executed by its canonical quest skill")
        if name in {"CAMERA_CONTROL", "REACQUIRE_TARGET"}:
            from .camera_controller import view_control_command
            params = {**params, "camera_action":
                "REACQUIRE_TRACK" if name == "REACQUIRE_TARGET" else params.get("camera_action")}
            return (view_control_command(params),)
        if name == "INSPECT" and params.get("camera_pan"):
            if not self.available(proposal, world):
                raise ValueError("Camera search preconditions missing")
            from .camera_controller import view_control_command
            return (view_control_command({**params, "camera_action": "INSPECT_REGION",
                                          "target_x": params.get("x"),
                                          "target_y": params.get("y")}),)
        if name == "INSPECT" and params.get("map_zoom_in"):
            if not self.available(proposal, world):
                raise ValueError("World Map zoom preconditions missing")
            return (Command("MAP_ZOOM_IN", x=params["x"], y=params["y"]),)
        if name == "INSPECT" and params.get("map_step_out"):
            if not self.available(proposal, world):
                raise ValueError("World Map parent-step preconditions missing")
            return (Command("MAP_STEP_OUT", x=params["x"], y=params["y"], button="RIGHT"),)
        if name == "WAIT":
            return ()
        if name == "TARGET" and params.get("restore_last_target"):
            return (Command("BIND", "TARGETLASTTARGET"),)
        if name in {"TARGET", "GATHER", "HERB", "MINE", "USE", "INSPECT"}:
            from .track_motion import candidate_for_track, predicted_point
            box = (candidate_for_track(world.state, params.get("track_id"))
                   if name in {"TARGET", "INSPECT"} and params.get("source") == "WORLD3D" else None)
            # A moving unit is hovered where it will be (user 2026-10-05).
            x, y = (predicted_point(box, world.state) if box is not None else None) or (params["x"], params["y"])
            return (Command("HOVER" if name == "INSPECT" else "CLICK", x=x, y=y,
                            button="RIGHT" if name in {"GATHER", "HERB", "MINE", "USE"} else "LEFT"),)
        if name == "REPAIR":
            return (Command("CLICK", x=params["x"], y=params["y"]),)
        if name in {"BUY_VENDOR", "SELL_VENDOR"}:
            return (Command("CLICK", x=params["x"], y=params["y"], button="RIGHT"),)
        if name == "OPEN_BAGS":
            return (Command("BIND", "OPENALLBAGS"),)
        if name == "DEATH_RECOVERY":
            return (Command("CLICK", x=params["x"], y=params["y"]),)
        if name == "LOOT" and params.get("corpse_anchor"):
            return (Command("CLICK", x=params["x"], y=params["y"], button="RIGHT"),)
        if name in {"LOOT", "INTERACT", "TALK", "ACQUIRE_TARGET"}:
            return (Command("BIND", "TARGETNEARESTENEMY" if name == "ACQUIRE_TARGET" else "INTERACTTARGET"),)
        if name in {"FISH", "MOUNT", "DISMOUNT"}:
            return (Command("BIND", params["binding"]),)
        if name in {"CLOSE_MAP", "OPEN_MAP"}:
            # TOGGLEWORLDMAP is not intrinsically idempotent.  Recheck the
            # current fast-lane state at dispatch so a delayed/replayed
            # proposal cannot invert an already achieved state.
            map_open = _world_map_open(world.state)
            if ((name == "CLOSE_MAP" and map_open is False)
                    or (name == "OPEN_MAP" and map_open is True)):
                return ()
            return (Command("BIND", "TOGGLEWORLDMAP"),)
        if name in {"COMBAT", "DEFEND"}:
            action = self.combat_action(world.state, record=True)
            if self.combat.needs_facing_recovery(world.state):
                # A WoW facing error proves the target is outside the forward
                # half-plane. A bounded ~pi-radian turn in either direction
                # places it inside the forward half-plane; split it into safe
                # <=350 ms input pulses, then retry the chosen ability in the
                # same verified combat attempt.
                pulse = min(.35, max(.2, math.pi / max(.5, self.turn_rate) / 3.))
                commands = [Command("BIND", "TURNLEFT", pulse) for _ in range(3)]
                self.combat.record_facing_recovery(world.state)
                if action is not None:
                    commands.append(Command("BIND", action["action"]))
                return tuple(commands)
            if action is None:
                return ()
            return (Command("BIND", action["action"]),)
        if name == "ASSIST":
            action = self.beneficial_action(world.state, params.get("item_id"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "EXIT_VEHICLE":
            return (Command("BIND", "VEHICLEEXIT"),)
        if name == "VEHICLE_ABILITY":
            # Refractory clock for the planner (1 s cooldown + lunge in flight).
            pressed = world.__dict__.setdefault("vehicle_ability_pressed_at", {})
            pressed[str(params.get("spell_id"))] = world.last_received
            return (Command("BIND", str(params["binding"])),)
        if name == "USE_ON_TARGET":
            if params.get("activation_source") == "INTERACT_KEY":
                return (Command("BIND", "INTERACTTARGET"),)
            action = self.quest_item_action(world.state, params.get("item_id"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "FOLLOW_INSTRUCTION":
            action = self.instructed_action(world.state, params.get("instruction"))
            return (Command("BIND", action["action"]),) if action else ()
        if name == "ESCAPE":
            return (Command("BIND", params["binding"], min(.3, max(.05, number(params.get("duration")) or .2))),)
        if name == "RECOVER":
            # The Navigation StuckResolver selects one evidence-gated step.
            # This execution layer merely maps that explicit step to one
            # bounded input request; it never advances the recovery ladder.
            step = str(params.get("recovery_step") or "STRAFE").upper()
            if step == "BACKWARD_REVEAL":
                # ~2.5 yd: a corpse under the character model comes into view.
                return (Command("BIND", "MOVEBACKWARD", .30), Command("BIND", "MOVEBACKWARD", .30))
            if step == "BACKWARD":
                # User 2026-10-02: back off clearly, not one step.  The
                # executor caps one input step at 350 ms, so ~0.9 s backwards
                # (about 4 yd) is three consecutive steps.
                return tuple(Command("BIND", "MOVEBACKWARD", .30) for _ in range(3))
            if step == "TURN":
                turn = "TURNLEFT" if params.get("attempt", 0) % 2 == 0 else "TURNRIGHT"
                return (Command("BIND", turn, .14),)
            if step == "JUMP_FORWARD":
                # Keep running through the jump arc so a low obstacle is cleared.
                return (Command("BIND", "MOVEFORWARD", .30, simultaneous=("JUMP",)),
                        Command("BIND", "MOVEFORWARD", .30))
            # Strafe away from a tagged obstacle when we can see roughly
            # where it is; fall back to bounded alternation when no obstacle
            # track is currently available.
            bearing = obstacle_bearing(world.state)
            if bearing is not None:
                side = "STRAFERIGHT" if bearing < .5 else "STRAFELEFT"
            else:
                side = "STRAFELEFT" if params.get("attempt", 0) % 2 == 0 else "STRAFERIGHT"
            return (Command("BIND", side, .25, simultaneous=("JUMP",)),)
        if name == "VISUAL_APPROACH":
            # The persistent VisualApproachController owns fast commands.
            return ()
        if name == "APPROACH_TARGET":
            screen = params.get("screen_position") or world.state["target"].get("screen_position") or {}
            x = screen["x"]
            error = x-.5
            if abs(error) > .08:
                turn = "TURNRIGHT" if error > 0 else "TURNLEFT"
                return (Command("BIND", "MOVEFORWARD", min(.15, max(.06, abs(error)*.45)), simultaneous=(turn,)),)
            return (Command("BIND", "MOVEFORWARD", .2),)
        if name == "MOVE":
            pos = world.player_position()
            dx, dy = params["x"] - pos[0], params["y"] - pos[1]
            dimensions = world.state.get("map_dimensions") or {}
            width, height = number(dimensions.get("width")), number(dimensions.get("height"))
            if width and height:
                dx, dy = dx * width, dy * height
            desired = math.atan2(-dx, -dy) % math.tau
            current = float(world.state["orientation"])
            error = (desired - current + math.pi) % math.tau - math.pi
            duration = min(.25, max(.06, (world.distance(params) or 0) * 15))
            if abs(error) > .12:
                turn = "TURNLEFT" if error > 0 else "TURNRIGHT"
                if self.bindings and not self.bindings.contains(turn):
                    raise ValueError(f"Hiányzó irányítási binding: {turn}")
                duration = min(duration, abs(error) / self.turn_rate, .18)
                return (Command("BIND", "MOVEFORWARD", duration, simultaneous=(turn,)),)
            return (Command("BIND", "MOVEFORWARD", duration),)
        raise ValueError(f"Nincs skill: {name}")
