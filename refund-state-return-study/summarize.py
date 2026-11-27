"""Summarize the matched refund matrix and independently replay its event ledger."""
import json

from run import DESIGN, HERE, RULES, ReturnWorkflow, fixture


def totals(rows):
    reached = [r for r in rows if r["old_observed_allowed"] is not None]
    denied = [r for r in reached if not r["old_observed_allowed"]]
    return {
        "runs": len(rows),
        "transport_errors": sum(r["transport_error"] for r in rows),
        "old_read_tested": len(reached),
        "old_reused": sum(r["old_observed_allowed"] for r in reached),
        "false_allow": sum(r["false_allow"] for r in reached),
        "false_reject": sum(r["false_reject"] for r in reached),
        "correct_commit": sum(r["correct_commit"] for r in rows),
        "old_denials": len(denied),
        "successful_recovery_commits": sum(r["correct_commit"] for r in denied),
        "tools_after_old_delivery": sum(r["tools_after_old_delivery"] for r in reached),
        "tools_after_old_denial": sum(r["tools_after_old_delivery"] for r in denied),
        "tool_calls": sum(len(r["tools"]) for r in rows),
        "fresh_prepares_after_old_delivery": sum(r["fresh_prepare_after_old_delivery"] for r in reached),
    }


def build_summary(rows):
    index = {(r["case"], r["arm"], r["seed"]): r for r in rows}
    expected = {
        (case, arm, seed)
        for case in DESIGN["cases"]
        for arm in DESIGN["arms"]
        for seed in DESIGN["seeds"]
    }
    if len(index) != len(rows) or index.keys() - expected:
        raise ValueError("Duplicate or unexpected assignment")
    case_summary = {}
    for case, scenario in DESIGN["cases"].items():
        matched = [
            {arm: index[case, arm, seed] for arm in DESIGN["arms"]}
            for seed in DESIGN["seeds"]
            if all(
                (case, arm, seed) in index
                and index[case, arm, seed]["old_observed_allowed"] is not None
                and not index[case, arm, seed]["transport_error"]
                for arm in DESIGN["arms"]
            )
        ]
        reference = ReturnWorkflow(fixture(case), "route_table", RULES)
        reference.status()
        reference.select_plan(["bank"])
        preparation = reference.prepare_read("bank")
        response = reference.call("read_fields", preparation)
        assert ("values" in response) == scenario["reuse"]
        assert [entry["kind"] for entry in reference.applied_changes] == scenario["events"]
        for run in rows:
            if run["case"] == case and run["old_observed_allowed"] is not None:
                assert run["state_transitions"] == reference.applied_changes
        case_summary[case] = {
            "expected_reuse": scenario["reuse"],
            "target": scenario["target"],
            "reference_event_ledger": reference.applied_changes,
            "matched_pairs": len(matched),
            "by_arm": {
                arm: totals([r for r in rows if r["case"] == case and r["arm"] == arm])
                for arm in DESIGN["arms"]
            },
            "matched_post_delivery_call_differences_contract_minus_table": [
                pair["contract"]["tools_after_old_delivery"] - pair["route_table"]["tools_after_old_delivery"]
                for pair in matched
            ],
        }
    return {
        "planned": len(expected),
        "completed": len(index),
        "complete": expected == index.keys(),
        "by_arm": {arm: totals([r for r in rows if r["arm"] == arm]) for arm in DESIGN["arms"]},
        "by_case": case_summary,
    }


if __name__ == "__main__":
    path = HERE / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    print(json.dumps(build_summary(rows), indent=2))
