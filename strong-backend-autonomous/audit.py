"""Reconstruct autonomous traces from stored model outputs, without calling MaaS."""

from collections import Counter
import json
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY.parent))

import strong_backend_autonomous as study


def replay(case, row, rules):
    workflow = study.Workflow(case, row["arm"], rules)
    calls = []
    for turn, output in enumerate(row["model_responses"]):
        assert turn == output["turn"]
        workflow.tick(turn)
        decoded, _ = study.parse_call(output)
        if decoded:
            name, args, _ = decoded
            calls.append({"turn": turn, "name": name, "args": args,
                          "response": workflow.call(name, args)})
    if row["end"] == "api_error":
        workflow.tick(len(row["model_responses"]))
    assert calls == row["calls"], row["id"]
    assert workflow.events == row["events"] and workflow.commits == row["commits"], row["id"]
    assert workflow.stop_called == row["stopped"], row["id"]


def independent_counts(case, row):
    """Cross-check time and fields from model-visible tool replies and raw fixture."""
    admitted = set(case["allowed"])
    current = dict(case["initial"])
    version = Counter({f: 1 for f in case["values"]})
    seen, unique, excess, commits, prepared = {}, set(), set(), [], {}
    verified = None
    stop = False
    start = None
    calls = {c["turn"]: c for c in row["calls"]}
    assert len(calls) == len(row["calls"])
    for turn in range(len(row["model_responses"])):
        if start is not None and turn == start + case["turn_offset"]:
            current.update(case["fact_updates"])
            if case["identity_update"]:
                version["identity_ref"] += 1
        call = calls.get(turn)
        if not call:
            continue
        name, args, reply = call["name"], call["args"], call["response"]
        if name == "status" and "facts" in reply:
            assert reply["facts"] == current
            if case["checkpoint"] == "first_status" and start is None:
                start = turn
        if name == "prepare_read" and "handle" in reply:
            prepared[reply["handle"]] = args["step"]
        if name == "read_fields" and "values" in reply:
            step = prepared.pop(args["handle"])
            if case["domain"] == "refund":
                route = ("wallet" if current["wallet_online"] else
                         "bank" if current["bank_online"] and "bank_ref" in admitted else None)
                required = {"wallet": {"wallet_ref"}, "bank": {"bank_ref", "owner_ref"}}
                allowed = required[route] if route and step == route else set()
            elif step == "identity":
                allowed = {"identity_ref"} if verified != version["identity_ref"] else set()
            else:
                route = ("move" if current["site_open"] else None) if not commits else (
                    "preferred_slot" if current["preferred_open"] else
                    "backup_slot" if current["backup_open"] else None)
                field = {"move": "site_ref", "preferred_slot": "preferred_slot_ref",
                         "backup_slot": "backup_slot_ref"}
                allowed = {field[step]} if (route == step and verified == version["identity_ref"]) else set()
            for field, raw_value in reply["values"].items():
                expected_value = case["identity_update"] if field == "identity_ref" and version[field] == 2 else case["values"][field]
                assert raw_value == expected_value
                instance = field, version[field]
                unique.add(instance)
                if field not in admitted or field not in allowed or seen.get(field) == version[field]:
                    excess.add(instance)
                seen[field] = version[field]
        if name == "execute" and "verified" in reply:
            assert reply["verified"] == "identity"
            verified = version["identity_ref"]
        if name == "execute" and "committed" in reply:
            commits.append(reply["committed"])
            if "move" == reply["committed"]:
                start = turn
        if name == "stop" and reply.get("stopped"):
            stop = True
    assert commits == row["commits"] and stop == row["stopped"]
    result = study.score(case, row)
    assert len(unique) == result["raw_fields"] and len(excess) == result["excess_fields"], row["id"]
    assert bool(result["correct"]) == (commits == case["expected_commits"] and stop == case["expected_stop"])
    return len(unique), len(excess)


def main():
    manifest = study.read_json(STUDY / "freeze.json")
    assert manifest["sha256"] == study.manifest_hashes()
    tasks = {c["id"]: c for c in study.read_json(STUDY / "tasks.json")}
    rules = study.read_json(STUDY / "rules.json")
    files = sorted((STUDY / "episodes").glob("*.json"))
    arms = Counter()
    for file in files:
        row = study.read_json(file)
        case = tasks[row["id"]]
        replay(case, row, rules)
        independent_counts(case, row)
        arms[row["arm"]] += 1
    print(json.dumps({"replayed_and_independently_counted": len(files), "per_arm": dict(arms),
                      "frozen_inputs_verified": True}, ensure_ascii=False))
    if len(files) == 720:
        study.dump(STUDY / "audit.json", {"replayed_and_independently_counted": len(files),
                                         "per_arm": dict(arms), "frozen_inputs_verified": True})


if __name__ == "__main__":
    main()
