"""PerceptionWorker perception context: reset keys, reset bookkeeping and UI-flag debounce.

Split out of perception.py (2026-10-05); unchanged.
"""
from __future__ import annotations


class PerceptionContextMixin:
    """Methods of PerceptionWorker (perception.py); moved verbatim."""

    @staticmethod
    def _stable_context_key(context, dimensions, allow, geometry):
        """Only reset temporal vision for a real scene/ROI transition.

        Cursor position and tooltip-probe state are per-frame attention hints.
        Including them in tracker identity invalidated every in-flight result
        while HOVER moved the cursor, exactly when fast confirmation mattered.
        """
        geometry = geometry or {}
        stable_geometry = tuple((name, geometry.get(name)) for name in (
            "visible", "center_x", "center_y", "radius_fraction",
            "world_map_open", "quest_ui_open", "gossip_open",
            # These alter projection/ROI semantics and must invalidate visual
            # tracks. Cursor/hover are deliberately absent: they are merely
            # active-perception hints and must not reset tracking.
            "ui_scale", "camera_zoom", "vehicle_camera"))
        return context, dimensions, bool(allow), stable_geometry

    def _record_context_reset(self, previous, key, now) -> None:
        """Name the key components whose change reset all visual tracking.

        Each reset restarts detector association and public track identity
        (live 2026-09-30: 28 resets in about a minute), so the cause must be
        visible in diagnostics rather than inferred.
        """
        changed: list[str] = []
        if previous is None:
            changed.append("initial")
        else:
            old_context, old_dimensions, old_allow, old_geometry = previous
            context, dimensions, allow, geometry = key
            if old_context != context:
                if isinstance(old_context, tuple) and isinstance(context, tuple) \
                        and len(old_context) == len(context):
                    changed.extend(
                        (self._CONTEXT_PARTS[index] if index < len(self._CONTEXT_PARTS)
                         else f"context[{index}]")
                        for index, (old, new) in enumerate(zip(old_context, context))
                        if old != new)
                else:
                    changed.append("context")
            if old_dimensions != dimensions:
                changed.append(f"dimensions:{old_dimensions}->{dimensions}")
            if old_allow != allow:
                changed.append(f"allow:{old_allow}->{allow}")
            old_values = dict(old_geometry)
            changed.extend(f"{name}:{old_values.get(name)!r}->{value!r}"
                           for name, value in geometry if old_values.get(name) != value)
        self.context_reset_count += 1
        self.context_reset_reasons.append({
            "at": round(float(now), 3), "changed": changed,
            "payload_kind": getattr(self, "_last_payload_kind", None)})
        for item in changed:
            field = item.split(":", 1)[0]
            self.context_reset_fields[field] = self.context_reset_fields.get(field, 0) + 1

    def _debounced_ui_flag(self, name: str, raw: bool, now: float) -> bool:
        """Effective UI flag: a change counts only after it persists.

        Live 2026-09-30: during OPEN_MAP the requested ``world_map_open``
        flipped 28 times in ~4 s (19-250 ms apart).  Every flip reset all
        visual tracking, the feed tracker and the stable object layer.  A real
        map/dialog transition persists; a sub-``ui_flag_debounce`` flip does
        not reset perception (raw flips stay counted for diagnosis).
        """
        state = self._ui_flags.get(name)
        if state is None:
            self._ui_flags[name] = [raw, raw, now]
            return raw
        effective, candidate, since = state
        if raw != candidate:
            self.ui_flag_raw_flips[name] = self.ui_flag_raw_flips.get(name, 0) + 1
        if raw == effective:
            state[1], state[2] = raw, now
            return effective
        if raw != candidate:
            state[1], state[2] = raw, now
            return effective
        if now - since >= self.ui_flag_debounce:
            state[0] = raw
            return raw
        return effective
