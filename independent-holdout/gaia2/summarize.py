"""Check the frozen run matrix and summarize the tracked release and recovery metrics."""
import argparse
from itertools import combinations
import json
from pathlib import Path


def totals(group):
    reached = [row for row in group if row["switch_observed"]]
    denied = [row for row in reached if row["denials"]]
    return {
        "runs": len(group),
        "upstream_successes": sum(row["upstream_success"] is True for row in group),
        "runtime_failures": sum(row["runtime_failure"] for row in group),
        "budget_exhausted_before_switch": sum(
            row["budget_exhausted"] and not row["switch_observed"] for row in group
        ),
        "switch_reached": len(reached),
        "stale_fields": sum(row["unique_stale_fields"] for row in group),
        "runs_with_stale_fields": sum(row["unique_stale_fields"] > 0 for row in group),
        "agent_tool_calls": sum(row["agent_tool_calls"] for row in group),
        "agent_model_calls": sum(row["agent_model_calls"] for row in group),
        "switch_reached_tool_calls_after_switch": sum(row["post_switch_tool_calls"] for row in reached),
        "denials": sum(row["denials"] for row in group),
        "denied_runs": len(denied),
        "denied_runs_recovered": sum(row["upstream_success"] is True for row in denied),
        "denied_runs_tool_calls_after_first_denial": sum(row["calls_after_first_denial"] for row in denied),
    }


def summarize(rows, rules):
    keys = [(r["case"], r["arm"], r["seed"]) for r in rows]
    expected = {
        (case, arm, seed)
        for case in rules["cases"]
        for arm in rules["arms"]
        for seed in rules["seeds"]
    }
    if len(set(keys)) != len(keys) or set(keys) - expected:
        raise ValueError("Duplicate or unexpected run keys")
    by_arm = {
        arm: [row for row in rows if row["arm"] == arm]
        for arm in rules["arms"]
    }
    paired = {}
    for left, right in combinations(rules["arms"], 2):
        left_rows = {(r["case"], r["seed"]): r for r in by_arm[left] if r["switch_observed"]}
        right_rows = {(r["case"], r["seed"]): r for r in by_arm[right] if r["switch_observed"]}
        common = left_rows.keys() & right_rows.keys()
        paired[f"{right}_minus_{left}"] = {
            "both_switched": len(common),
            "post_switch_tool_call_differences": [
                {
                    "case": case,
                    "seed": seed,
                    "delta": right_rows[case, seed]["post_switch_tool_calls"]
                    - left_rows[case, seed]["post_switch_tool_calls"],
                }
                for case, seed in sorted(common)
            ],
        }
    return {
        "planned": len(expected),
        "completed": len(rows),
        "complete": set(keys) == expected,
        "by_arm": {arm: totals(group) for arm, group in by_arm.items()},
        "by_case_and_arm": {
            case: {
                arm: totals([row for row in group if row["case"] == case])
                for arm, group in by_arm.items()
            }
            for case in rules["cases"]
        },
        "matched_switch_comparisons": paired,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    rules = json.loads(Path(__file__).with_name("protocol.json").read_text())
    rows = [json.loads(line) for line in args.results.read_text().splitlines()]
    print(json.dumps(summarize(rows, rules), indent=2))
