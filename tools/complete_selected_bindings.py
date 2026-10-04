"""Explicit, operator-approved completion from observed GetBindingKey evidence.

Never run automatically. Does not discover a different cache or change existing
assignments. Backs up exact original bytes and refuses conflicting key mappings.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime


def additions(raw: str, state: dict):
    assigned, commands = {}, set()
    for line in raw.splitlines():
        match = re.fullmatch(r'\s*bind\s+(?:"([^"]+)"|(\S+))\s+(?:"([^"]*)"|(\S+))\s*', line, re.I)
        if match:
            key, command = (match[1] or match[2]).upper(), (match[3] or match[4] or "").upper()
            assigned[key] = command
    commands = set(assigned.values())
    evidence = [(action, value.get("primary"), value.get("source")) for action, value in state.get("control_bindings", {}).items()]
    evidence += [(a.get("action"), a.get("binding_primary"), "GET_BINDING_KEY") for a in state.get("actionbar", [])]
    rows = []
    for action, key, source in evidence:
        if not action or not key or source != "GET_BINDING_KEY" or action in commands:
            continue
        if any(c in key+action for c in '"\r\n'):
            raise ValueError("Unsafe binding field")
        if key in assigned and assigned[key] != action:
            raise ValueError(f"Existing assignment conflicts: {key} → {assigned[key]}, observed {action}")
        rows.append(f'bind "{key}" "{action}"')
        assigned[key], commands = action, commands | {action}
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    status = json.loads(args.status.read_text(encoding="utf-8"))
    if args.cache.resolve() != Path(status["bindings_cache"]).resolve():
        raise ValueError("Must match the explicitly selected cache")
    raw = args.cache.read_bytes()
    if status.get("bindings_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Cache changed since selection")
    state = status["world"]["player"]
    if not state.get("control_bindings"):
        raise ValueError("No client-confirmed control binding telemetry")
    rows = additions(raw.decode("utf-8-sig"), state)
    print("\n".join(rows) or "No additions")
    if args.apply and rows:
        args.backup.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (args.backup / f"bindings-cache-{stamp}.wtf").write_bytes(raw)
        (args.backup / f"binding-evidence-{stamp}.json").write_text(json.dumps({"control_bindings": state["control_bindings"],
             "actionbar": state.get("actionbar"), "session": state.get("session_id"), "source_sha256": status["bindings_sha256"]}, indent=2), encoding="utf-8")
        args.cache.write_bytes(raw + b"\r\n" + ("\r\n".join(rows)+"\r\n").encode("utf-8"))
        print("Applied with backup; reload selected cache in agent before FULL_AI.")


if __name__ == "__main__":
    main()
