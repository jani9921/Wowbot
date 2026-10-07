"""Observed client bindings are evidence, never an executor fallback."""
from .models import canonical
from adapters.atomic_file import write_json_replace


class BindingInventory:
    def __init__(self, output, cache, pid):
        self.path = output / "client_bindings.json"
        self.cache, self.pid = cache, pid
        self.identity = None
        self.pages = {}
        self.signature = None
        self.next_write = 0.
        self.status = {"status": "waiting_for_addon_catalog", "complete": False}
        self.report = None
        self.supported = False
        self.control_bindings = {}

    @staticmethod
    def _keys(binding):
        if not isinstance(binding, dict):
            return []
        return [str(binding.get(field)).upper() for field in ("primary", "secondary")
                if isinstance(binding.get(field), str) and binding.get(field)]

    def validate_actions(self, actions) -> dict:
        """Fail closed when exact-PID client evidence disagrees with the selected cache."""
        required = sorted({str(action).upper() for action in actions if action})
        if not self.supported:
            # No catalog page yet, but live control_bindings from the selected
            # client are still exact evidence; a contradiction must block
            # (issue #77). Actions without evidence stay permissive here.
            mismatches = []
            for action in required:
                if action in self.control_bindings:
                    client = self._keys(self.control_bindings[action])
                    selected = [str(key).upper() for key in self.cache.actions.get(action, [])]
                    if client != selected:
                        mismatches.append({"action": action, "client": client,
                                           "selected_cache": selected})
            return {"ready": not mismatches, "supported": False,
                    "mismatches": mismatches, "unverified": []}
        observed = {str(action).upper(): self._keys(binding)
                    for action, binding in self.control_bindings.items()}
        report = self.report or {}
        for row in report.get("bindings", []):
            if isinstance(row, dict) and row.get("action"):
                observed.setdefault(str(row["action"]).upper(), self._keys(row))
        for row in report.get("actionbar", []):
            if isinstance(row, dict) and row.get("action"):
                observed.setdefault(str(row["action"]).upper(), [
                    str(key).upper() for key in row.get("client_keys", []) if key])
        complete = report.get("complete") is True
        mismatches, unverified = [], []
        for action in required:
            if action not in observed:
                if complete:
                    observed[action] = []
                else:
                    unverified.append(action)
                    continue
            client = observed[action]
            selected = [str(key).upper() for key in self.cache.actions.get(action, [])]
            if client != selected:
                mismatches.append({"action": action, "client": client,
                                   "selected_cache": selected})
        return {"ready": not mismatches and not unverified, "supported": True,
                "mismatches": mismatches, "unverified": unverified,
                "complete": complete}

    def ingest(self, state, now):
        self.report = None  # Invalid/absent pages must not leave an importable old snapshot.
        if "binding_catalog_page" in state:
            self.supported = True
        controls = state.get("control_bindings")
        if isinstance(controls, dict):
            self.control_bindings = {str(action).upper(): binding for action, binding in controls.items()
                                     if isinstance(binding, dict)}
        page = state.get("binding_catalog_page") or {}
        if page.get("status") != "ok":
            self.status = {"status": "waiting_for_addon_catalog", "complete": False}
            return
        index, count, total = page.get("page"), page.get("pages"), page.get("count")
        if any(type(v) is not int for v in (index, count, total)) or not (0 <= index < count <= 625 and 0 <= total <= 10000):
            self.status = {"status": "invalid_catalog_page", "complete": False}
            return
        rows = page.get("rows")
        if rows == {} and total == 0: rows = []  # Lua empty-table encoding
        expected = min(16, max(0, total-index*16))
        if count != max(1, (total+15)//16) or not isinstance(rows, list) or len(rows) != expected:
            self.status = {"status": "invalid_catalog_page", "complete": False}
            return
        if any(not isinstance(r, dict) or any(not isinstance(r.get(k), str) for k in ("action", "category", "primary", "secondary")) for r in rows):
            return
        identity = (state.get("session_id"), state.get("character_guid"), page.get("revision"), page.get("binding_set"), count, total)
        if identity != self.identity:
            self.identity, self.pages = identity, {}
        self.pages[index] = rows
        merged = [r for p in sorted(self.pages) for r in self.pages[p]]
        observed = {r["action"]: [k for k in (r["primary"], r["secondary"]) if k] for r in merged}
        differences = [{"action": a, "client": keys, "selected_cache": self.cache.actions.get(a.upper(), [])}
                       for a, keys in observed.items() if keys != self.cache.actions.get(a.upper(), [])]
        spells = [{"slot": a.get("slot"), "kind": a.get("kind"), "id": a.get("id"), "name": a.get("name"),
                   "action": a.get("action"), "client_keys": [k for k in (a.get("binding_primary"), a.get("binding_secondary")) if k],
                   "selected_cache_keys": self.cache.actions.get(str(a.get("action") or "").upper(), [])}
                  for a in state.get("actionbar", [])]
        complete = len(self.pages) == count
        report = {"source": "ADDON_GET_BINDING", "pid": self.pid, "session_id": identity[0], "character_guid": identity[1],
                  "revision": identity[2], "binding_set": identity[3], "complete": complete,
                  "pages_received": len(self.pages), "pages_expected": count, "count_expected": total,
                  "bindings": merged, "actionbar": spells, "control_bindings": self.control_bindings,
                  "differences": differences,
                  "selected_cache": str(self.cache.path), "selected_cache_sha256": self.cache.digest,
                  "authoritative_for_input": False}
        self.status = {"status": "complete" if complete else "collecting", "complete": complete,
                       "pages_received": len(self.pages), "pages_expected": count, "differences": len(differences), "path": str(self.path)}
        self.report = {**report, "received_at": now}
        signature = canonical(report)
        if signature != self.signature and now >= self.next_write:
            write_json_replace(self.path, {**report, "received_at": now})
            self.signature, self.next_write = signature, now+1.


def create_controller_cache(report, output, *, pid, session_id, character_guid, now):
    """Explicit export, not a merge: unbound actions remain unbound. Never overwrite."""
    from pathlib import Path
    import uuid
    from .bindings import BindingsCache, BindingError
    from .models import number
    if not isinstance(report, dict) or report.get("complete") is not True or report.get("source") != "ADDON_GET_BINDING":
        raise BindingError("A teljes kliens-binding export még nem érkezett meg.")
    if not session_id or not character_guid or (report.get("pid"), report.get("session_id"), report.get("character_guid")) != (pid, session_id, character_guid):
        raise BindingError("Az export nem a csatlakoztatott PID/karakter aktuális munkamenetéből származik.")
    received = number(report.get("received_at"))
    if received is None or not 0 <= now-received <= 30:
        raise BindingError("Elavult export: frissítsd a kliens megfigyelését, majd próbáld újra.")
    rows = report.get("bindings")
    count = report.get("count_expected")
    pages = report.get("pages_expected")
    if (not isinstance(rows, list) or type(count) is not int or not 0 <= count <= 10000
        or len(rows) != count or pages != max(1, (count+15)//16) or report.get("pages_received") != pages):
        raise BindingError("Hiányos vagy hibás binding-katalógus.")
    assigned, actions, lines = {}, set(), []
    claims = {}
    for row in rows:
        if not isinstance(row, dict): continue
        for field in ("primary", "secondary"):
            key = row.get(field)
            if isinstance(key, str) and key:
                claims.setdefault(key.upper(), []).append(row)
    resolved = {}
    for key, candidates in claims.items():
        if len({r.get("action") for r in candidates}) <= 1:
            continue
        evidence = []
        for row in candidates:
            for field in ("primary", "secondary"):
                if str(row.get(field, "")).upper() == key:
                    evidence.append(row.get(f"normal_{field}_action"))
        if (not all(isinstance(a, str) and a for a in evidence)
            or len(set(evidence)) != 1 or evidence[0] not in {r.get("action") for r in candidates}):
            raise BindingError(f"Ütköző binding: {key}. Friss addon-export kell a normál binding-környezet igazolásához.")
        resolved[key] = evidence[0]
    def safe_token(value):
        return isinstance(value, str) and not any(ord(c) < 32 or c in '\\"' or ord(c) == 127 for c in value)
    for row in rows:
        if not isinstance(row, dict) or not all(safe_token(row.get(k)) for k in ("action", "primary", "secondary")):
            raise BindingError("Érvénytelen karakter a binding-exportban.")
        action = row["action"]
        if not action or action.upper() in actions:
            raise BindingError("Hiányzó vagy ismétlődő binding-parancs az exportban.")
        actions.add(action.upper())
        for key in (row["primary"], row["secondary"]):
            if not key: continue
            if key.upper() in resolved and resolved[key.upper()] != action:
                continue  # Explicit GetBindingAction(..., BindingContext.None) evidence, not category guessing.
            if action.upper() == "NONE":
                raise BindingError("Érvénytelen NONE parancshoz rendelt billentyű.")
            if key.upper() in assigned:
                if assigned[key.upper()] != action.upper():
                    raise BindingError(f"Ütköző binding: {key}. Nem választunk önkényesen parancsot.")
                continue
            assigned[key.upper()] = action.upper()
            lines.append(f'bind "{key}" "{action}"')
    if not lines:
        raise BindingError("Az exportban nincs kiosztott billentyű.")
    directory = Path(output) / "controller-caches"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"bindings-cache-pid-{pid}-{uuid.uuid4().hex[:12]}.wtf"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines)+"\n")
    cache = BindingsCache(path)
    write_json_replace(path.with_suffix(".json"), {"pid": pid, "session_id": session_id,
        "character_guid": character_guid, "source_revision": report.get("revision"),
        "source_received_at": received, "sha256": cache.digest,
        "original_cache": report.get("selected_cache"), "auto_selected": False})
    return path
