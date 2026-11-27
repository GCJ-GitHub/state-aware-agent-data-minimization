"""Validate the matrix and compare matched attempts at the delivery boundary."""
from collections import Counter
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "protocol.json").read_text())


def metrics(rows):
    exposed = [row for row in rows if row.get("model_saw_reply")]
    denied = [row for row in exposed if row["model_saw_denial"]]
    return {
        "assigned": len(rows),
        "passed_upstream": sum(row.get("upstream_success") is True for row in rows),
        "runtime_or_transport_errors": sum(row["transport_or_runtime_error"] for row in rows),
        "started_probe": sum(row.get("started_probe", False) for row in rows),
        "crossed_before_delivery": sum(row.get("crossed_window", False) for row in rows),
        "reply_reached_model": len(exposed),
        "stale_fields_to_model": sum(row["stale_fields_to_model"] for row in exposed),
        "denials_reached_model": len(denied),
        "denials_recovered": sum(row["upstream_success"] is True for row in denied),
        "native_tool_calls_after_denial": sum(row["native_calls_after_switch"] for row in denied),
    }


def summarize(rows):
    groups = {}
    for row in rows:
        assert row["case"] in SPEC["cases"] and row["seed"] in SPEC["seeds"]
        assert row["arm"] in SPEC["arms"]
        group = groups.setdefault((row["case"], row["seed"]), {})
        if row["arm"] in group:
            raise ValueError("Duplicate run")
        group[row["arm"]] = row
        if row.get("model_saw_reply"):
            assert row["crossed_window"] and row["delivery_epoch"] > row["old_epoch"]
            assert row["stale_fields_to_model"] == int(not row["model_saw_denial"])
    matched = [
        group for _, group in sorted(groups.items())
        if len(group) == len(SPEC["arms"])
        and all(row.get("model_saw_reply") and not row["transport_or_runtime_error"] for row in group.values())
    ]
    return {
        "planned": len(SPEC["cases"]) * len(SPEC["seeds"]) * len(SPEC["arms"]),
        "completed": len(rows),
        "all_runs_by_arm": {
            arm: metrics([row for row in rows if row["arm"] == arm]) for arm in SPEC["arms"]
        },
        "matched_triplets": len(matched),
        "matched_by_arm": {
            arm: {
                **metrics(selected := [group[arm] for group in matched]),
                "native_tool_calls": sum(row["native_tool_calls"] for row in selected),
                "native_tool_calls_after_switch": sum(row["native_calls_after_switch"] for row in selected),
            }
            for arm in SPEC["arms"]
        },
        "matched_rows": [
            {
                "case": group["agent"]["case"],
                "seed": group["agent"]["seed"],
                "after_switch_calls": {
                    arm: group[arm]["native_calls_after_switch"] for arm in SPEC["arms"]
                },
                "success": {arm: group[arm]["upstream_success"] for arm in SPEC["arms"]},
            }
            for group in matched
        ],
    }


if __name__ == "__main__":
    path = HERE / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    print(json.dumps(summarize(rows), indent=2))
