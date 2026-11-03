"""Pure confirmation rules for a bounded, explicitly addressed quest dialog."""
from __future__ import annotations

from wowbot.runtime import FailureReason, VerificationResult
from .quest import QuestProgressVerifier
from wowbot.agent.quest_ui_evidence import dialog_recipient


def _sequence(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _events_after_baseline(before: dict, after: dict) -> list:
    """Only events newer than the pre-click state may prove a transition.

    Issue #82: the rolling event list still held an earlier QUEST_ACCEPTED/
    QUEST_TURNED_IN for the same quest, so a later click was confirmed with
    unchanged before/after state.
    """
    old_events = [e for e in before.get("events") or () if isinstance(e, dict)]
    known = [_sequence(before.get("event_sequence"))]
    known += [_sequence(e.get("sequence")) for e in old_events]
    known = [value for value in known if value is not None]
    baseline = max(known) if known else None
    fresh = []
    for event in after.get("events") or ():
        if not isinstance(event, dict):
            continue
        sequence = _sequence(event.get("sequence"))
        if sequence is not None and baseline is not None:
            if sequence > baseline:
                fresh.append(event)
        elif event not in old_events:
            fresh.append(event)
    return fresh


class QuestDialogVerifier:
    """Verify dialog transition without clicking or selecting a reward."""

    def evaluate(self, before: dict, after: dict, *, quest_id: object | None,
                 action: str, reward_choice_index: object | None = None,
                 target_guid: object | None = None,
                 gossip_option_id: object | None = None,
                 gossip_transition: str = "SCRIPTED_COMBAT") -> VerificationResult:
        wanted = str(quest_id) if quest_id is not None else None
        events = _events_after_baseline(before, after)
        matching = {
            str(event.get("event_type") or "").upper()
            for event in events if isinstance(event, dict)
            and (wanted is None or str((event.get("payload") or {}).get("quest_id")) == wanted)
        }
        old_ids = {str(row.get("quest_id")) for row in before.get("active_quests") or ()
                   if isinstance(row, dict) and row.get("quest_id") is not None}
        new_ids = {str(row.get("quest_id")) for row in after.get("active_quests") or ()
                   if isinstance(row, dict) and row.get("quest_id") is not None}
        old_accepted = {str(value) for value in before.get("accepted_quest_ids") or ()}
        new_accepted = {str(value) for value in after.get("accepted_quest_ids") or ()}
        if action == "GOSSIP_VENDOR":
            # The vendor row opened the shop.
            opened = ((after.get("vendor_ui") or {}).get("open") is True
                      and (before.get("vendor_ui") or {}).get("open") is not True)
            return VerificationResult(opened, .95 if opened else 0., None,
                                      (f"gossip_vendor_opened:{gossip_option_id}",) if opened else ())
        if action == "GOSSIP_OPTION_SELECT":
            old_target, new_target = dialog_recipient(before), after.get("target") or {}
            if not target_guid or str(old_target.get("guid") or "") != str(target_guid):
                return VerificationResult(False, 0., FailureReason.WRONG_QUEST_UI)
            old_ui, new_ui = before.get("quest_ui") or {}, after.get("quest_ui") or {}
            old_option = old_ui.get("gossip_option") or before.get("quest_ui_gossip_option") or {}
            listed = any(isinstance(row, dict) and str(row.get("id")) == str(gossip_option_id)
                         for row in old_ui.get("gossip_options") or ())
            if str(old_option.get("id")) != str(gossip_option_id) and not listed:
                return VerificationResult(False, 0., FailureReason.WRONG_QUEST_UI)
            if gossip_transition == "SCENE_START":
                # A course started again (2026-10-25, the Skytop race): a new
                # scene runs, or the start line roots the rider.
                old_scene, new_scene = before.get("packet_scene") or {}, after.get("packet_scene") or {}
                old_root, new_root = before.get("movement_rooted") or {}, after.get("movement_rooted") or {}
                started = (new_scene.get("active") is True
                           and new_scene.get("scene_instance_id") != old_scene.get("scene_instance_id"))
                rooted = (new_root.get("rooted") is True
                          and (new_root.get("sampled_at") or 0) > (old_root.get("sampled_at") or 0))
                return VerificationResult(started or rooted, .95 if started or rooted else 0., None,
                                          (f"scene_course_restarted:{gossip_option_id}",) if started or rooted else ())
            objective_ids = []
            for quest in before.get("active_quests") or ():
                if str(quest.get("quest_id")) == wanted:
                    for index, objective in enumerate(quest.get("objectives") or ()):
                        oid = str(objective.get("objective_id") or index)
                        objective_ids.append(oid if oid.startswith(f"{wanted}:") else f"{wanted}:{oid}")
            progress = QuestProgressVerifier().evaluate(
                before, {**after, "events": events}, quest_ids=[wanted], objective_ids=objective_ids)
            if progress.success:
                return VerificationResult(True, .98, None,
                    (f"gossip_option_advanced:{wanted}:{gossip_option_id}", *progress.evidence))
            if gossip_transition == "QUEST_PROGRESS":
                # A transformation/conversation is not a scripted duel. An
                # unrelated mob starting combat cannot confirm this choice.
                # A script may also replace/clear the NPC's spawn GUID before
                # delayed credit arrives (live 2026-10-15). This is only a
                # no-input WAIT: never rebind identity, click or retarget the
                # replacement. Only this quest's credit (above) or the skill
                # deadline may end it.
                return VerificationResult(False, 0., None)
            if str(new_target.get("guid") or "") != str(target_guid):
                # A duel script may clear selection before attackability is
                # reported. Keep a bounded no-input wait; a different GUID
                # never inherits this NPC's identity or confirms the choice.
                return VerificationResult(False, 0., FailureReason.WRONG_QUEST_UI if new_target.get("guid") else None)
            # A click alone is not completion. For this scripted-fight dialogue,
            # wait for the same NPC to become attackable or for combat to start.
            transitioned = (new_target.get("attackable", new_target.get("is_attackable")) is True
                            and old_target.get("attackable", old_target.get("is_attackable")) is not True)
            combat_started = (after.get("is_in_combat") is True
                              and before.get("is_in_combat") is not True)
            confirmed = transitioned or combat_started
            return VerificationResult(confirmed, .95 if confirmed else .0, None,
                                      (f"gossip_option_advanced:{wanted}:{gossip_option_id}",)
                                      if confirmed else ())
        if action == "GOSSIP_SELECT":
            ui = after.get("quest_ui") or {}
            observed_action = str(ui.get("action") or after.get("quest_ui_action") or "").upper()
            observed_quest = ui.get("quest_id")
            if observed_quest is None:
                observed_quest = after.get("quest_ui_quest_id")
            # The row click is only a successful selection when the client
            # presents a subsequent, explicitly named action for the exact
            # same quest.  A UI close, unrelated row, or merely changed pixels
            # is not sufficient evidence.
            known_quest = observed_quest not in (None, "", 0, "0", False)
            selected = (known_quest and observed_action in {"ACCEPT", "COMPLETE", "TURN_IN", "CONTINUE"}
                        and wanted is not None and str(observed_quest) == wanted)
            wrong_quest = known_quest and wanted is not None and str(observed_quest) != wanted
            return VerificationResult(selected, .95 if selected else .0,
                                      FailureReason.WRONG_QUEST_UI if wrong_quest else None,
                                      (f"gossip_selected:{wanted}",) if selected else ())
        if action == "REWARD_SELECT":
            ui = after.get("quest_ui") or {}
            wanted_index = str(reward_choice_index) if reward_choice_index is not None else ""
            selected_index = ui.get("reward_selected_index")
            if wanted_index and selected_index is not None and str(selected_index) == wanted_index:
                return VerificationResult(True, .98, None, (f"reward_selected:{wanted}:{wanted_index}",))
            if wanted_index and selected_index not in (None, 0, "", "0"):
                return VerificationResult(False, 0., FailureReason.WRONG_QUEST_UI)
            selected_rows = [row for row in ui.get("reward_choices") or ()
                             if isinstance(row, dict) and row.get("selected") is True]
            if wanted_index and any(str(row.get("index")) == wanted_index for row in selected_rows):
                return VerificationResult(True, .98, None, (f"reward_selected:{wanted}:{wanted_index}",))
            if selected_rows:
                return VerificationResult(False, 0., FailureReason.WRONG_QUEST_UI)
            return VerificationResult(False, 0., None)
        if action == "ACCEPT":
            accepted = ((wanted is not None and wanted in new_ids-old_ids)
                        or (wanted is not None and wanted in new_accepted-old_accepted)
                        or "QUEST_ACCEPTED" in matching)
            return VerificationResult(accepted, .98 if accepted else .0, None,
                                      (f"quest_accepted:{wanted}",) if accepted else ())
        if action in {"COMPLETE", "TURN_IN"}:
            from wowbot.agent.quest_receipts import fresh_turn_in_receipt
            receipt = fresh_turn_in_receipt(before, after, wanted)
            complete = "QUEST_TURNED_IN" in matching or receipt is not None
            return VerificationResult(complete, .98 if complete else .0, None,
                                      ((f"quest_turned_in:{wanted}",)
                                       + ((f"turn_in_receipt:{receipt['sequence']}",) if receipt else ()))
                                      if complete else ())
        if action == "CONTINUE":
            old_ui, new_ui = before.get("quest_ui") or {}, after.get("quest_ui") or {}
            changed = (new_ui.get("open") is not True
                       or (new_ui.get("action"), new_ui.get("quest_id")) !=
                          (old_ui.get("action"), old_ui.get("quest_id")))
            return VerificationResult(changed, .7 if changed else .0, None,
                                      ("dialog_transition",) if changed else ())
        return VerificationResult(False, 1., FailureReason.WRONG_QUEST_UI)
