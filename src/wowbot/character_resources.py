"""One static DB2 unit conversion, shared by query and combat consumers."""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=4)
def _references(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('schema') != 'aipc.power-reference.v1'
                or not re.fullmatch('[a-f0-9]{64}', str(data.get('source_sha256', '')))
                or not re.fullmatch('[a-f0-9]{64}', str(data.get('definition_sha256', '')))):
            return {}
        rows = {}
        for value in data['rows']:
            kind, divisor = value['power_type'], value['display_modifier']
            if (type(kind) is not int or not 0 <= kind <= 255 or kind in rows
                    or type(divisor) is not int or not 0 < divisor <= 100_000
                    or type(value['minimum_raw']) is not int):
                return {}
            rows[kind] = {**value, 'source_sha256': data['source_sha256'],
                          'definition_sha256': data['definition_sha256'],
                          'layout_hash': data.get('layout_hash'), 'live_build_verified': False}
        return rows
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def resource_reference(power_type, path=None):
    if type(power_type) is not int:
        return None
    source = Path(path) if path is not None else Path(__file__).resolve().parents[2]/'data/client_power_types.json'
    row = _references(str(source)).get(power_type)
    return dict(row) if row else None


def display_power(raw, reference):
    if type(raw) is not int or reference is None or raw < reference['minimum_raw']:
        return None
    return raw/reference['display_modifier']
