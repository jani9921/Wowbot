"""REV4 visual retirement step 3 (P4 audit 6.2, user 2026-10-30): the SERVER
composition never moves the pointer onto a screen box to acquire a unit or a
corpse.  The dispatcher already withheld the HOVER/POINTER, so a hover-confirm
skill waited out its whole deadline for a confirmation that never came; now
it takes the key path (Tab/Interact) or fails at once with a typed reason."""
import ast
from pathlib import Path

from wowbot.agent.models import Attempt, Prediction, Proposal
from wowbot.agent.pointer_tracking import follow_pointer, live_pointer_point
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.skills import TargetSkill
from wowbot.skills.hover_confirm import hover_confirm_step, live_track_point, pointer_acquisition_retired
from wowbot.skills.interact import InteractSkill
from wowbot.skills.loot import LootSkill

GUID = "Creature-0-1-2-3-4-5"
SERVER = {"runtime_profile": "SERVER"}
BOX = {"source": "WORLD3D", "track_id": "t1", "x": .5, "y": .5, "observed_at": 10., "lifecycle": "ACTIVE"}


def _active(skill, params, deadline=8.):
    proposal = Proposal.make(skill, "test", params)
    attempt = Attempt("a", proposal, {"target": {}}, "o", 1., deadline, (),
                      Prediction("p", "a", "target", 1., deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent(skill, params, params.get("guid")), attempt=attempt, now=1.)
    return runtime.state


def test_the_retirement_marker_is_the_server_profile():
    assert pointer_acquisition_retired(SERVER)
    assert not pointer_acquisition_retired({}) and not pointer_acquisition_retired(None)


def test_hover_confirm_fails_at_once_and_no_track_is_aimed_in_server():
    context = {"hovered_at": 10., "hovers": 1, "hover_point": (.5, .5), "track_id": "t1"}
    fresh = {"mouseover": {"guid": GUID}, "mouseover_sample_time": 10.05, "visual_candidates": [BOX]}
    assert hover_confirm_step(dict(context), fresh, 10.2, expected_guid=GUID)[0] == "CLICK"
    assert hover_confirm_step(dict(context), {**fresh, **SERVER}, 10.2, expected_guid=GUID) == ("FAILED", ())
    assert live_track_point({"visual_candidates": [BOX]}, "t1") is not None
    assert live_track_point({"visual_candidates": [BOX], **SERVER}, "t1") is None
    assert live_pointer_point({"visual_candidates": [BOX], **SERVER}, "t1", 10.1) is None
    assert follow_pointer({}, {**SERVER, "visual_candidates": [BOX]}, "t1", 10.1, point=(.4, .4)) is None


def test_server_target_never_hovers_or_clicks_a_screen_point():
    params = {"guid": GUID, "hover_x": .5, "hover_y": .5, "x": .5, "y": .5}
    legacy = TargetSkill().begin(_active("TARGET", params), {})
    assert legacy.commands[0].kind == "HOVER"
    result = TargetSkill().begin(_active("TARGET", params), SERVER)
    assert result.status is SkillStatus.FAILURE and result.reason is FailureReason.LOW_CONFIDENCE
    assert result.metadata["detail"] == "pointer_acquisition_retired" and not result.commands
    tab = Intent("TARGET", {"guid": GUID, "activation_source": "TAB_SERVER_GUID"}, GUID)
    assert [c.binding for c in TargetSkill().commands_for(tab)] == ["TARGETNEARESTENEMY"]   # the key path stays


def test_server_interact_presses_the_key_without_hovering_the_target_box():
    world = {"target": {"guid": GUID, "attackable": False, "npc_id": 4,
                        "screen_position": {"x": .5, "y": .5, "bbox": {"left": .45, "bottom": .4,
                                                                       "right": .55, "top": .6}}},
             "monotonic_time": 1., "target_sample_time": 1.}
    legacy = InteractSkill().begin(_active("INTERACT", {"guid": GUID}), world)
    assert legacy.commands[0].kind == "HOVER"
    result = InteractSkill().begin(_active("INTERACT", {"guid": GUID}), {**world, **SERVER})
    assert result.status is SkillStatus.RUNNING
    assert [(c.kind, c.binding) for c in result.commands] == [("BIND", "INTERACTTARGET")]


def test_server_loot_never_hovers_a_remembered_corpse_point():
    params = {"guid": GUID, "corpse_anchor": True, "x": .5, "y": .6}
    legacy = LootSkill().begin(_active("LOOT", params), {})
    assert legacy.commands[0].kind == "HOVER"
    result = LootSkill().begin(_active("LOOT", params), SERVER)
    assert result.status is SkillStatus.FAILURE and result.reason is FailureReason.CORPSE_NOT_FOUND
    assert result.metadata["detail"] == "pointer_acquisition_retired"
    soft = {**SERVER, "soft_targets": [{"source_unit": "softinteract", "guid": GUID, "is_dead": True}]}
    keyed = LootSkill().begin(_active("LOOT", params), soft)
    assert [(c.kind, c.binding) for c in keyed.commands] == [("BIND", "INTERACTTARGET")]


# HOVERs that never move the pointer: OBJECT_USE re-hovers the exact point
# the cursor already rests on (begin() rejects any point >.002 away from it)
# to force a fresh addon sample before its right-click.
SAME_POINT_REHOVER = {("wowbot/skills/object_use.py", "begin"), ("wowbot/skills/object_use.py", "verify")}
# Helpers whose every caller is gated.
GATED_BY_CALLER = {("wowbot/skills/interact.py", "_hover_command"),   # begin/verify use gated hover_points
                   ("wowbot/skills/hover_confirm.py", "hover_confirm_step")}  # gated in its own first line


def test_every_skill_pointer_aim_is_server_gated():
    src = Path(__file__).resolve().parents[1] / "src"
    ungated = []
    for path in sorted((src / "wowbot/skills").rglob("*.py")):
        relative = path.relative_to(src).as_posix()
        text = path.read_text(encoding="utf-8-sig")
        for function in [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef)]:
            aims = [n for n in ast.walk(function) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == "Command" and n.args
                    and isinstance(n.args[0], ast.Constant) and n.args[0].value in {"HOVER", "POINTER"}]
            key = (relative, function.name)
            if not aims or key in SAME_POINT_REHOVER or key in GATED_BY_CALLER:
                continue
            if "pointer_acquisition_retired(" not in (ast.get_source_segment(text, function) or ""):
                ungated.append(f"{relative}:{function.name}")
    assert ungated == []
