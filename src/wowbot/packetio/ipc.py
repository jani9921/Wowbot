"""Authenticated local IPC, unrelated to game/session secrets."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def envelope(event, descriptor, *, stream=None):
    body = {"schema": "aipc.packet-envelope.v1", "context": descriptor["context"], "event": event}
    if stream is not None:
        from .delivery import stamp
        body.update(schema='aipc.packet-envelope.v2', stream=stamp(stream))
    return {**body, "signature": hmac.new(descriptor["ipc_key"].encode(), canonical(body), hashlib.sha256).hexdigest()}


def verify(value, descriptor):
    if not isinstance(value, dict) or value.get("schema") not in {"aipc.packet-envelope.v1", "aipc.packet-envelope.v2"}:
        raise ValueError("authenticated packet envelope required")
    body = {k: value.get(k) for k in ("schema", "context", "event")}
    if value['schema'] == 'aipc.packet-envelope.v2':
        from .delivery import stamp
        body['stream'] = stamp(value.get('stream'))
    expected = hmac.new(descriptor["ipc_key"].encode(), canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(value.get("signature") or "")):
        raise ValueError("invalid packet IPC signature")
    if value.get("context") != descriptor.get("context"):
        raise ValueError("packet runtime/session context changed")
    return value.get("event")


def read_descriptor(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema") != "aipc.packet-endpoint.v1"
            or value.get("host") != "127.0.0.1" or type(value.get("port")) is not int
            or not 0 < value["port"] < 65536 or not isinstance(value.get("context"), dict)
            or not isinstance(value.get("ipc_key"), str) or len(value["ipc_key"]) < 32):
        raise ValueError("invalid or inactive packet endpoint")
    return value
