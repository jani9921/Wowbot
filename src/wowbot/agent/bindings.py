from __future__ import annotations

import hashlib
from pathlib import Path
import re


class BindingError(RuntimeError):
    pass


class BindingsCache:
    """Only the explicitly selected WTF file is authoritative; never scan/fallback."""

    def __init__(self, path: Path):
        self.path = path.resolve(strict=True)
        self.actions: dict[str, list[str]] = {}
        self.digest = ""
        self.reload()

    def reload(self):
        raw = self.path.read_bytes()
        actions: dict[str, list[str]] = {}
        assigned: dict[str, str] = {}
        for line in raw.decode("utf-8-sig").splitlines():
            match = re.fullmatch(r'\s*bind\s+(?:"([^"]+)"|(\S+))\s+(?:"([^"]*)"|(\S+))\s*', line, re.I)
            if match:
                key, command = (match[1] or match[2]).upper(), (match[3] or match[4] or "").upper()
                assigned[key] = command
        for key, command in assigned.items():
            if command and command != "NONE":
                actions.setdefault(command, []).append(key)
        if not actions:
            raise BindingError(f"Nincsenek bind sorok a kiválasztott fájlban: {self.path}")
        self.actions, self.digest = actions, hashlib.sha256(raw).hexdigest()

    def resolve(self, action: str) -> str:
        keys = self.actions.get(action.upper())
        if not keys:
            raise BindingError(f"Hiányzó binding a kiválasztott cache-ben: {action}")
        return keys[0]

    def contains(self, action: str) -> bool:
        return isinstance(action, str) and action.upper() in self.actions

    def unchanged(self) -> bool:
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest() == self.digest
        except OSError:
            return False

    def required_actions(self, domain: str, actionbar=()) -> list[str]:
        required = {"QUEST": ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT", "JUMP", "INTERACTTARGET", "TARGETNEARESTENEMY"),
                    "MOVE": ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                    "EXPLORE": ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                    "HERB": ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT"),
                    "MINE": ("MOVEFORWARD", "TURNLEFT", "TURNRIGHT")}.get(domain, ())
        actions = list(required)
        if domain == "QUEST":
            actions.extend(a.get("action") for a in actionbar
                           if a.get("is_harmful") is True and a.get("action"))
        return sorted(set(actions))

    def preflight(self, domain: str, actionbar=()) -> dict:
        required = self.required_actions(domain, actionbar)
        missing = [action for action in required if not self.contains(action)]
        return {"ready": not missing, "missing": sorted(set(missing)), "path": str(self.path), "sha256": self.digest}


class NoBindingsCache(BindingsCache):
    """No cache file selected yet (fresh PC): an export-only session.

    User 2026-10-03: connecting must work without a bindings cache so the
    addon's binding export can create one.  Every binding is missing, so the
    executor refuses all key input and the FULL_AI preflight refuses to arm;
    only telemetry and the binding export run.
    """

    def __init__(self):
        self.path = None
        self.actions: dict[str, list[str]] = {}
        self.digest = ""

    def reload(self):
        return None

    def unchanged(self) -> bool:
        return True

    def resolve(self, action: str) -> str:
        raise BindingError(f"Nincs kiválasztott bindings-cache (csak export mód): {action}")
