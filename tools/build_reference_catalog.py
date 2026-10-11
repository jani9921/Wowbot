"""Import selected TDB world/DB2 data without executing the SQL dump."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wowbot.agent.reference_catalog import build_reference

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path)
    parser.add_argument("--hotfixes", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_reference(args.world, args.hotfixes, args.output), indent=2))
