"""Query local client DB2 alongside the existing TDB; never copies or mutates it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wowbot.agent.reference_catalog import ReferenceCatalog
from wowbot.quests.client_catalog import ClientCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--quest", type=int)
    selection.add_argument("--scene", type=int)
    selection.add_argument("--path", type=int)
    selection.add_argument("--item", type=int)
    selection.add_argument("--area-trigger", type=int)
    selection.add_argument("--conversation-line", type=int)
    selection.add_argument("--record", nargs=2, metavar=("TABLE", "ID"))
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--tdb", type=Path, help="Existing WORLD database (optional override)")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    client = ClientCatalog(args.catalog)
    if args.quest is not None:
        world = ReferenceCatalog(args.tdb)
        try:
            tdb = world.quest(args.quest)
            result = {"quest_id": args.quest, "tdb": tdb,
                      "client_db2": client.quest(args.quest, details=args.details),
                      "scene_resolution": client.scene_resolution(args.quest, details=args.details),
                      "status": "REFERENCE_ONLY_REQUIRES_LIVE_OBJECTIVES_AND_CONTEXT"}
            if args.details:
                result["tdb_script_references"] = world.quest_scripts(args.quest)
        finally:
            world.close()
    elif args.scene is not None:
        result = client.scene(args.scene)
    elif args.path is not None:
        result = client.path_nodes(args.path)
    elif args.item is not None:
        result = client.item_use(args.item)
    elif args.area_trigger is not None:
        result = client.supplement.area_trigger(args.area_trigger)
    elif args.conversation_line is not None:
        result = client.supplement.conversation_line(args.conversation_line)
    elif args.record:
        result = client.record(args.record[0], int(args.record[1]))
    else:
        result = client.diagnostics()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
