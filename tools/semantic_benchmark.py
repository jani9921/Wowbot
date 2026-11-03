"""Measure a local Ollama model on the semantic_advisor tasks.

    python tools/semantic_benchmark.py --model llama3.2:3b
    python tools/semantic_benchmark.py --model qwen2.5:3b --num-gpu 0
    python tools/semantic_benchmark.py --tdb --facts           # Exile's Reach from the local TDB
    python tools/semantic_benchmark.py --tdb --facts --escalation-model qwen3:4b-thinking-2507-q4_K_M

Runs every case in data/semantic_benchmark/cases.json through the same
prompts/validation the agent uses and prints per-case results plus accuracy
and latency; the summary is also written to output/semantic_benchmark/.

``--tdb`` instead builds the Exile's Reach cases from the local TDB (quest
text, TDB facts, quest enders) and scores them against
data/semantic_benchmark/exiles_reach_gold.json; ``--facts`` gives the model
the TDB facts, ``--escalation-model`` re-asks doubtful answers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wowbot.agent.semantic_advisor import (DEFAULT_CONFIG, TASKS, SemanticAdvisor,  # noqa: E402
                                           ability_request, doubtful, objective_key, quest_requests,
                                           speech_request, tdb_objective_facts, turnin_request)


def _same(value, accepted) -> bool:
    accepted = accepted if isinstance(accepted, list) else [accepted]
    if value is None:
        return None in accepted
    return any(isinstance(item, str) and item.casefold() == str(value).casefold() for item in accepted)


def _run(task: str, payload: dict, config: dict, transport=None) -> tuple[dict | None, float, str | None]:
    system, validate = TASKS[task]
    started = time.monotonic()
    try:
        raw = (transport or SemanticAdvisor._http)(system, payload, config)
        return validate(payload, raw), time.monotonic()-started, None
    except Exception as error:
        return None, time.monotonic()-started, f"{type(error).__name__}: {error}"


def tdb_cases(gold: dict, provider) -> list[dict]:
    """Exile's Reach cases: quest text, TDB facts and enders from the local TDB."""
    raw = provider.catalog.raw

    def names(record, role):
        result = []
        for row in (record or {}).get("quest_roles") or ():
            if row.get("role") == role and row.get("npc_id") is not None:
                npc = raw.npc(row["npc_id"]) if raw else None
                if npc and npc.get("name"):
                    result.append(npc["name"])
        return sorted(dict.fromkeys(result))
    cases = []
    wanted = {quest["quest_id"]: quest for quest in gold.get("quests") or ()}
    turnins = set(gold.get("turnin_quests") or ())
    for quest_id in sorted(set(wanted) | turnins):
        record = provider.quest(quest_id)
        if not record:
            continue
        cases.append({
            "quest_id": quest_id, "title": record.get("title") or "",
            "texts": {"description": record.get("description") or "",
                      "objectives_text": record.get("objectives_text") or "",
                      "completion_text": record.get("completion_text") or "",
                      "giver_name": ", ".join(names(record, "QUEST_STARTER"))},
            "objectives": (wanted.get(quest_id) or {}).get("objectives") or [],
            "facts": tdb_objective_facts(record),
            "enders": names(record, "QUEST_ENDER"),
            "turnin": quest_id in turnins})
    return cases


def run_tdb_cases(cases: list[dict], config: dict, *, use_facts: bool, escalation: dict | None = None,
                  transport=None, show=print) -> dict:
    """Score objective actions/targets and turn-in names; returns the summary."""
    score = {"action": [0, 0], "target": [0, 0], "turnin": [0, 0]}
    escalations, latencies = 0, []

    def ask(task, payload):
        nonlocal escalations
        result, spent, error = _run(task, payload, config, transport)
        latencies.append(spent)
        if escalation and doubtful(task, payload, result):
            escalations += 1
            second, more, _ = _run(task, payload, {**config, **escalation}, transport)
            latencies[-1] += more
            if second is not None:
                result = second
        return result

    def mark(name, ok):
        score[name][0] += int(bool(ok))
        score[name][1] += 1
        return "ok" if ok else "XX"

    for case in cases:
        quest = {"quest_id": case["quest_id"], "title": case["title"],
                 "objectives": [{"description": item["text"]} for item in case["objectives"]]}
        result = {}
        for _, payload in quest_requests(quest, case["texts"],
                                         facts=case["facts"] if use_facts else None):
            result.update((ask("quest", payload) or {}).get("objectives") or {})
        for expected in case["objectives"]:
            got = result.get(objective_key(expected["text"])) or {}
            action_ok = mark("action", got.get("action") in expected["action"])
            target_ok = mark("target", _same(got.get("target"), expected.get("target", [None])))
            show(f"{case['quest_id']} {expected['text'][:46]:<46} {str(got.get('action')):<19} "
                 f"{action_ok} t={got.get('target')!s:<24} {target_ok}")
        if case.get("turnin") and case.get("enders"):
            request = turnin_request({"quest_id": case["quest_id"], "title": case["title"]},
                                     case["texts"], case["enders"] if use_facts else None)
            if request is not None:
                name = (ask("turnin", request[1]) or {}).get("name")
                show(f"{case['quest_id']} turn-in -> {name!s:<28} gold={case['enders']} "
                     f"{mark('turnin', _same(name, case['enders']))}")
    return {"facts": use_facts, "escalation": (escalation or {}).get("model"),
            "accuracy": {name: (f"{good}/{total}" if total else "-") for name, (good, total) in score.items()},
            "escalations": escalations,
            "latency_s": {"median": sorted(latencies)[len(latencies)//2] if latencies else None,
                          "total": round(sum(latencies), 1)}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_CONFIG["model"])
    parser.add_argument("--num-gpu", type=int, default=0)
    parser.add_argument("--num-thread", type=int, default=4)
    parser.add_argument("--cases", default=str(ROOT / "data" / "semantic_benchmark" / "cases.json"))
    parser.add_argument("--whole-quest", action="store_true", help="one question per quest, not per objective")
    parser.add_argument("--tdb", action="store_true", help="Exile's Reach cases from the local TDB")
    parser.add_argument("--facts", action="store_true", help="give the model the TDB facts (with --tdb)")
    parser.add_argument("--escalation-model", default=None, help="re-ask doubtful answers with this model")
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--gold", default=str(ROOT / "data" / "semantic_benchmark" / "exiles_reach_gold.json"))
    args = parser.parse_args()
    config = {**DEFAULT_CONFIG, "model": args.model, "num_gpu": args.num_gpu, "num_thread": args.num_thread,
              "num_ctx": args.num_ctx}
    if args.tdb:
        from wowbot.agent.reference_catalog import ReferenceCatalog, default_reference_path
        from wowbot.agent.tdb_knowledge import TDBKnowledgeProvider
        catalog = ReferenceCatalog(default_reference_path())
        if catalog.raw is None:
            print("No TDB found: see docs/TDB_SETUP.md")
            return 1
        cases = tdb_cases(json.loads(Path(args.gold).read_text(encoding="utf-8")),
                          TDBKnowledgeProvider(catalog))
        escalation = {"model": args.escalation_model, "think": True} if args.escalation_model else None
        summary = {"model": args.model, **run_tdb_cases(cases, config, use_facts=args.facts,
                                                        escalation=escalation)}
        print(json.dumps(summary, indent=1))
        out = ROOT / "output" / "semantic_benchmark"
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        mode = "facts" if args.facts else "nofacts"
        (out / f"{stamp}-tdb-{mode}-{args.model.replace(':', '_')}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    score = {"action": [0, 0], "target": [0, 0], "item": [0, 0], "mode": [0, 0],
             "instruction": [0, 0], "ability": [0, 0]}
    latencies, rows = [], []

    def mark(name, ok):
        score[name][0] += int(bool(ok))
        score[name][1] += 1
        return "ok" if ok else "XX"

    for quest in cases["quests"]:
        raw_quest = {"quest_id": quest["quest_id"], "title": quest["title"], "description": quest.get("description"),
                     "objectives": [{"description": item["text"]} for item in quest["objectives"]]}
        result, latency, error = {"objectives": {}}, 0., None
        for key, payload in quest_requests(raw_quest, {"description": quest.get("description")},
                                           per_objective=not args.whole_quest):
            part, spent, failure = _run("quest", payload, config)
            latency += spent
            error = error or failure
            result["objectives"].update((part or {}).get("objectives") or {})
        latencies.append(latency)
        for expected in quest["objectives"]:
            got = ((result or {}).get("objectives") or {}).get(objective_key(expected["text"])) or {}
            line = [quest["source"][0], f"{latency:5.1f}s", expected["text"][:44].ljust(44),
                    f"{str(got.get('action')):<20}", mark("action", got.get("action") in expected["action"]),
                    f"t={got.get('target')!s:<22}", mark("target", _same(got.get("target"), expected.get("target", [None])))]
            if "item" in expected or got.get("item"):
                line += [f"i={got.get('item')}", mark("item", _same(got.get("item"), expected.get("item", [None])))]
            if error:
                line.append(error[:80])
            rows.append(" ".join(line))
            print(rows[-1], flush=True)

    for ability in cases["abilities"]:
        key, payload = ability_request(ability, ())
        result, latency, error = _run("ability", payload, config)
        latencies.append(latency)
        mode = (result or {}).get("mode")
        rows.append(f"{ability['source'][0]} {latency:5.1f}s ability {ability['name']:<20} {str(mode):<14} "
                    f"{mark('mode', mode in ability['mode'])} {error or ''}")
        print(rows[-1], flush=True)

    for speech in cases["speech"]:
        key, payload = speech_request({"payload": {"sender": speech["speaker"], "message": speech["line"]}},
                                      {}, speech["abilities"])
        result, latency, error = _run("speech", payload, config)
        latencies.append(latency)
        result = result or {}
        rows.append(f"{speech['source'][0]} {latency:5.1f}s speech  {speech['line'][:44]:<44} "
                    f"instr={result.get('instruction')!s:<5} {mark('instruction', result.get('instruction') == speech['instruction'])} "
                    f"ability={result.get('ability')} {mark('ability', _same(result.get('ability'), speech['ability']))} {error or ''}")
        print(rows[-1], flush=True)

    summary = {"model": args.model, "num_gpu": args.num_gpu, "num_thread": args.num_thread,
               "per_objective": not args.whole_quest,
               "accuracy": {name: (f"{good}/{total}" if total else "-") for name, (good, total) in score.items()},
               "latency_s": {"median": sorted(latencies)[len(latencies)//2] if latencies else None,
                             "max": max(latencies) if latencies else None,
                             "total": round(sum(latencies), 1)}}
    print(json.dumps(summary, indent=1))
    out = ROOT / "output" / "semantic_benchmark"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"{stamp}-{args.model.replace(':', '_')}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
