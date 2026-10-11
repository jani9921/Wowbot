"""Read the reference catalogue without starting the WoW agent or client input."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wowbot.agent.reference_catalog import ReferenceCatalog
from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--quest", type=int)
    parser.add_argument("--npc", type=int)
    parser.add_argument("--name")
    parser.add_argument('--services', type=int, help='NPC service/gossip/vendor/trainer knowledge')
    parser.add_argument('--item', type=int, help='Quest item and vendor source candidates')
    parser.add_argument('--table', help='Allowlisted knowledge table')
    parser.add_argument('--id', type=int, help='Typed lookup key for --table')
    args = parser.parse_args()
    catalog = ReferenceCatalog(args.database)
    provider = TDBKnowledgeProvider(catalog)
    try:
        result = {"catalogue": catalog.diagnostics()}
        if args.quest is not None:
            result["quest"] = provider.quest(args.quest)
        if args.npc is not None:
            result["npc"] = catalog.npc(args.npc)
        if args.name:
            result["name_candidates"] = catalog.find_by_name(args.name)
        if args.services is not None:
            result['services'] = provider.services(args.services)
        if args.item is not None:
            result['item_sources'] = provider.item_sources(args.item)
        if args.table and args.id is not None:
            result['records'] = provider.lookup(args.table, args.id)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if catalog.available else 1
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
