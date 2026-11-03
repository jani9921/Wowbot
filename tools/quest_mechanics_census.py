"""Census of quest objective mechanisms (TDB + client DB2, read-only).

Classifies every objective with the same ``objective_mechanics.classify``
the runtime quest reference uses. It writes:
- ``docs/QUEST_MECHANICS.md``: counts per expansion, our coverage, a
  backlog and examples;
- ``output/quest_mechanics.json``: per quest and objective.

A static census is knowledge, not live validation (AGENTS.md).

    python tools/quest_mechanics_census.py [--tdb PATH] [--catalog PATH]
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wowbot.agent.reference_catalog import default_reference_path                      # noqa: E402
from wowbot.agent.tdb_knowledge import (_ASK_ABOUT, _BUY_VENDOR, _ORDERS_RECEIVED,       # noqa: E402
                                        _RIDE_CREDIT, _TALK_CREDIT)
from wowbot.quests.client_catalog import default_catalog_path                           # noqa: E402
from wowbot.quests.objective_mechanics import (COVERAGE, ESCORT_TEXT, Db2IndexFacts,    # noqa: E402
                                               TdbIndexFacts, classify, objective_facts)

EXPANSIONS = {9: "Dragonflight", 10: "The War Within", 11: "Midnight"}
STATUS_ORDER = {"NONE": 0, "PARTIAL": 1, "LIVE": 2, "OUT_OF_SCOPE": 3}
EXAMPLES = 4


def credit_action(credit_name, description):
    """The TDB provider's text reading of TALK/RIDE/BUY (tdb_knowledge)."""
    name, text = str(credit_name or ""), str(description or "").strip()
    if _BUY_VENDOR.search(text):
        return "BUY"
    if _TALK_CREDIT.search(name) or _ORDERS_RECEIVED.fullmatch(text) or _ASK_ABOUT.fullmatch(text):
        return "TALK"
    if _RIDE_CREDIT.search(name):
        return "RIDE"
    return None


def census(tdb: Path, catalog: Path) -> dict:
    with closing(sqlite3.connect(tdb.as_uri() + "?mode=ro", uri=True)) as world_db, \
            closing(sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True)) as client_db:
        world, db2 = TdbIndexFacts(world_db), Db2IndexFacts(client_db)
        quests = {row[0]: row for row in world_db.execute(
            "SELECT ID, LogTitle, LogDescription, QuestDescription, Expansion, StartItem, "
            "ItemDrop1, ItemDrop2, ItemDrop3, ItemDrop4 FROM quest_template")}
        addon = {row[0]: row for row in world_db.execute(
            "SELECT ID, SourceSpellID, ScriptName FROM quest_template_addon")}
        objectives = world_db.execute(
            'SELECT QuestID, ID, Type, ObjectID, Description FROM quest_objectives ORDER BY QuestID, "Order"').fetchall()
    result = defaultdict(list)
    for quest_id, objective_id, kind, entry, description in objectives:
        quest = quests.get(quest_id)
        if quest is None:
            continue
        extra = addon.get(quest_id) or (quest_id, None, None)
        creature = world.creature(entry) if kind == 0 else None
        facts = objective_facts(
            world, db2, kind=kind, credit_entry=entry, credit_name=(creature or {}).get("name"),
            credit_action=credit_action((creature or {}).get("name"), description),
            quest_items=bool(quest[5] or extra[1] or any(quest[6:10])),
            escort=bool(ESCORT_TEXT.search(" ".join(str(part or "") for part in quest[1:4]))),
            scripted_quest=bool(extra[2]), description=description)
        result[quest_id].append({"objective_id": objective_id, "type": kind, "credit_entry": entry,
                                 "description": description or "", **classify(facts)})
    # Share the exact ItemEffect -> objective association with runtime.
    # A missing supplement leaves the older structural classifier usable.
    from wowbot.quests.client_supplement import ClientSupplement
    from wowbot.agent.quest_item_knowledge import annotate_items
    supplement = ClientSupplement(catalog.with_name("client_supplement.sqlite3"))
    if supplement.path.is_file():
        for qid, rows in result.items():
            quest = quests[qid]
            if not (quest[5] or any(quest[6:10])):
                continue
            refs = [{**row, "credit_object_id": row["credit_entry"],
                     "credit_kind": {0: "CREATURE_CREDIT", 1: "ITEM"}.get(row["type"]),
                     "mechanism_tags": row["tags"]} for row in rows]
            reference = {"items": {"start_item_id": quest[5], "drop_item_ids": quest[6:10]},
                         "objectives": refs}
            annotate_items(reference, supplement)
            for row, ref in zip(rows, refs):
                row.update(mechanism=ref["mechanism"], tags=ref["mechanism_tags"], item_uses=ref["item_uses"])
    return {"quests": quests, "objectives": result}


def expansion_of(quest) -> str:
    return EXPANSIONS.get(quest[4], "other")


def report(data: dict, tdb: Path) -> str:
    quests, objectives = data["quests"], data["objectives"]
    columns = [*EXPANSIONS.values(), "other"]
    counts = defaultdict(Counter)
    quest_counts = defaultdict(Counter)
    tags = defaultdict(Counter)
    examples = defaultdict(list)
    for quest_id, rows in objectives.items():
        quest = quests[quest_id]
        column = expansion_of(quest)
        for mechanism in {row["mechanism"] for row in rows}:
            quest_counts[mechanism][column] += 1
        for row in rows:
            counts[row["mechanism"]][column] += 1
            for tag in row["tags"]:
                tags[tag][column] += 1
            if column != "other" and len(examples[row["mechanism"]]) < EXAMPLES:
                examples[row["mechanism"]].append(
                    f"{quest_id} {quest[1]} — {row['description'] or '(hidden)'}")
    recent = set(EXPANSIONS.values())
    total_objectives = sum(sum(counter.values()) for counter in counts.values())
    lines = [
        "# Quest objective mechanisms (census)",
        "",
        f"Generated by `tools/quest_mechanics_census.py` on {date.today().isoformat()} from "
        f"`{tdb.name}` + `data/client_reference.sqlite3` and optional sibling `client_supplement.sqlite3` (read-only).",
        "",
        "The runtime quest reference uses the same classifier"
        " (`src/wowbot/quests/objective_mechanics.py`, field `objective['mechanism']`).",
        "This census is static knowledge, not live validation.",
        "",
        "What it cannot see:",
        "- what the server's scripts do after a gossip (attack, speech, an object opening);",
        "- missing/ambiguous quest-item links and script-only credit: ItemEffect now supplies explicit item/spell/credit links when present;",
        "",
        "Unknown sources therefore stay `SPELL_CREDIT` or `UNRESOLVED`.",
        "",
        f"{len(objectives)} quests, {total_objectives} objectives.",
        "",
        "Status:",
        "- **LIVE**: validated in a live run;",
        "- **PARTIAL**: some cases, or offline only;",
        "- **NONE**: no handler;",
        "- **OUT_OF_SCOPE**: not planned now.",
        "",
        "## Coverage",
        "",
        "Objective counts per expansion; the quest count is in parentheses.",
        "",
        "| Mechanism | Status | Handler | " + " | ".join(columns) + " | Evidence |",
        "|---|---|---|" + "---|" * len(columns) + "---|",
    ]
    order = sorted(counts, key=lambda name: (-sum(counts[name][c] for c in recent), name))
    for name in order:
        status, handler, evidence = COVERAGE.get(name, ("NONE", "-", ""))
        cells = " | ".join(f"{counts[name][c]} ({quest_counts[name][c]})" for c in columns)
        lines.append(f"| `{name}` | {status} | {handler} | {cells} | {evidence} |")
    lines += ["", "## Backlog (not live, by recent-expansion objectives)", "",
              "| Mechanism | Status | Recent objectives | Recent quests |", "|---|---|---|---|"]
    backlog = [name for name in order if COVERAGE.get(name, ("NONE",))[0] in {"NONE", "PARTIAL"}]
    backlog.sort(key=lambda name: (STATUS_ORDER[COVERAGE.get(name, ("NONE",))[0]],
                                   -sum(counts[name][c] for c in recent)))
    for name in backlog:
        recent_objectives = sum(counts[name][c] for c in recent)
        recent_quests = sum(quest_counts[name][c] for c in recent)
        if recent_objectives:
            lines.append(f"| `{name}` | {COVERAGE.get(name, ('NONE',))[0]} | {recent_objectives} | {recent_quests} |")
    lines += ["", "## Tags", "", "| Tag | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    for name in sorted(tags):
        lines.append(f"| `{name}` | " + " | ".join(str(tags[name][c]) for c in columns) + " |")
    lines += ["", "## Examples (Dragonflight / The War Within / Midnight)", ""]
    for name in order:
        if examples[name]:
            lines.append(f"- `{name}`")
            lines += [f"  - {example}" for example in examples[name]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tdb", type=Path, default=default_reference_path())
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "QUEST_MECHANICS.md")
    parser.add_argument("--json", type=Path, default=ROOT / "output" / "quest_mechanics.json")
    args = parser.parse_args(argv)
    for path in (args.tdb, args.catalog):
        if not path.is_file():
            parser.error(f"missing read-only source: {path}")
    data = census(args.tdb.resolve(), args.catalog.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report(data, args.tdb), encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({str(quest_id): {"title": data["quests"][quest_id][1],
                                                     "expansion": data["quests"][quest_id][4],
                                                     "objectives": rows}
                                     for quest_id, rows in data["objectives"].items()}, ensure_ascii=False),
                         encoding="utf-8")
    print(f"{len(data['objectives'])} quests -> {args.report} and {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
