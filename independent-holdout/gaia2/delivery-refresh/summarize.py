"""Summarize first assignments and matched observable delivery windows."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN = json.loads((HERE / "protocol.json").read_text())
UPSTREAM = json.loads((HERE.parent / "delivery-window" / "protocol.json").read_text())


def summarize(rows):
    cells = {
        (case, seed, arm)
        for case in UPSTREAM["cases"]
        for seed in UPSTREAM["seeds"]
        for arm in DESIGN["arms"]
    }
    seen = {}
    for row in rows:
        key = row["case"], row["seed"], row["arm"]
        if key not in cells or key in seen:
            raise ValueError(f"Unexpected or repeated run {key}")
        if row.get("model_saw_reply"):
            assert row["delivery_epoch"] > row["old_epoch"]
            assert row["stale_fields_to_model"] == int(not row["model_saw_denial"])
        seen[key] = row

    def scores(group):
        visible = [r for r in group if r.get("model_saw_reply")]
        denied = [r for r in visible if r.get("model_saw_denial")]
        return {
            "runs": len(group),
            "runtime_errors": sum(r["transport_or_runtime_error"] for r in group),
            "upstream_passes": sum(r.get("upstream_success") is True for r in group),
            "window_observed_by_model": len(visible),
            "old_values_to_model": sum(r["stale_fields_to_model"] for r in visible) if visible else None,
            "denials": len(denied),
            "denials_recovered": sum(r.get("upstream_success") is True for r in denied),
            "native_calls_after_switch": sum(r["native_calls_after_switch"] for r in visible) if visible else None,
            "agent_responses": sum(r.get("agent_responses", 0) for r in group),
        }

    pairs = []
    for case in UPSTREAM["cases"]:
        for seed in UPSTREAM["seeds"]:
            pair = {arm: seen.get((case, seed, arm)) for arm in DESIGN["arms"]}
            if all(r and r.get("model_saw_reply") and not r["transport_or_runtime_error"] for r in pair.values()):
                pairs.append((case, seed, pair))
    return {
        "planned": len(cells),
        "completed": len(seen),
        "complete": cells == seen.keys(),
        "by_arm": {arm: scores([r for r in rows if r["arm"] == arm]) for arm in DESIGN["arms"]},
        "matched_pairs": len(pairs),
        "matched_by_arm": {arm: scores([p[arm] for _, _, p in pairs]) for arm in DESIGN["arms"]},
        "matched_rows": [
            {
                "case": case,
                "seed": seed,
                "passed": {arm: row["upstream_success"] for arm, row in pair.items()},
                "native_calls_after_switch": {arm: row["native_calls_after_switch"] for arm, row in pair.items()},
            }
            for case, seed, pair in pairs
        ],
    }


if __name__ == "__main__":
    path = HERE / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    print(json.dumps(summarize(rows), indent=2))
