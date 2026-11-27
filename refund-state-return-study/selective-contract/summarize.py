"""Check full pairing and report autorization, completion and call totals."""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
DESIGN = json.loads((HERE / "protocol.json").read_text())
PARENT = json.loads((HERE.parent / "protocol.json").read_text())


def counts(rows):
    reached = [r for r in rows if r["old_observed_allowed"] is not None]
    denied = [r for r in reached if not r["old_observed_allowed"]]
    return {
        "runs": len(rows),
        "transport_errors": sum(r["transport_error"] for r in rows),
        "correct_commit": sum(r["correct_commit"] for r in rows),
        "old_reads_tested": len(reached),
        "old_reuses": sum(r["old_observed_allowed"] for r in reached),
        "must_reject": sum(not r["old_expected_allowed"] for r in reached),
        "could_reuse": sum(r["old_expected_allowed"] for r in reached),
        "false_allow": sum(r["false_allow"] for r in reached),
        "false_reject": sum(r["false_reject"] for r in reached),
        "denials": len(denied),
        "recovered_commits": sum(r["correct_commit"] for r in denied),
        "fresh_prepares_after_old_delivery": sum(r["fresh_prepare_after_old_delivery"] for r in reached),
        "calls_after_old_delivery": sum(r["tools_after_old_delivery"] for r in reached),
        "total_tool_calls": sum(len(r["tools"]) for r in rows),
    }


def summarize(rows):
    index = {(r["case"], r["arm"], r["seed"]): r for r in rows}
    keys = {
        (case, arm, seed)
        for case in PARENT["cases"]
        for arm in DESIGN["arms"]
        for seed in PARENT["seeds"]
    }
    if len(index) != len(rows) or index.keys() - keys:
        raise ValueError("Duplicate or unexpected assignment")

    matched = []
    for case, spec in PARENT["cases"].items():
        for seed in PARENT["seeds"]:
            group = {arm: index.get((case, arm, seed)) for arm in DESIGN["arms"]}
            if not all(r and r["old_observed_allowed"] is not None and not r["transport_error"] for r in group.values()):
                continue
            assert all(r["old_expected_allowed"] == spec["reuse"] for r in group.values())
            expected_events = spec["events"]
            assert all([t["kind"] for t in r["state_transitions"]] == expected_events for r in group.values())
            matched.append({
                "case": case,
                "seed": seed,
                "old_read_allowed": {a: r["old_observed_allowed"] for a, r in group.items()},
                "correct_commit": {a: r["correct_commit"] for a, r in group.items()},
                "calls_after_old_delivery": {a: r["tools_after_old_delivery"] for a, r in group.items()},
            })
    return {
        "planned": len(keys),
        "completed": len(index),
        "complete": index.keys() == keys,
        "by_arm": {arm: counts([r for r in rows if r["arm"] == arm]) for arm in DESIGN["arms"]},
        "by_case": {
            case: {
                arm: counts([r for r in rows if r["case"] == case and r["arm"] == arm])
                for arm in DESIGN["arms"]
            }
            for case in PARENT["cases"]
        },
        "matched_triples": len(matched),
        "matched": matched,
    }


if __name__ == "__main__":
    path = HERE / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    print(json.dumps(summarize(rows), indent=2))
