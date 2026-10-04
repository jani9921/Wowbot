from __future__ import annotations

import json
from pathlib import Path


def test_json_output_is_valid_array_container(tmp_path: Path) -> None:
    p = tmp_path / 'minimap_observation.json'
    samples = [{"markers": []}, {"markers": [{"type": "target"}]}]
    p.write_text(json.dumps({"samples": samples}, indent=2), encoding='utf-8')
    data = json.loads(p.read_text(encoding='utf-8'))
    assert isinstance(data["samples"], list)
    assert data["samples"][1]["markers"][0]["type"] == "target"
