"""Score frozen async-delivery cases using the independent field labels."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
RULES = json.loads((HERE / "protocol.json").read_text())
GOLD = json.loads((HERE / "gold.json").read_text())["after_first_native_cancel"]
LATENCY = ("prepare_to_reply_ms", "report_hold_ms", "event_observed_to_reply_ms", "decision_ms")


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    index = 0.95 * (len(values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    p95 = values[lower] + (index - lower) * (values[upper] - values[lower])
    return {"n": len(values), "median": round(statistics.median(values), 6), "p95": round(p95, 6)}


def score(rows):
    decided = [row for row in rows if row.get("model_saw_reply")]
    successes = [row for row in rows if row.get("upstream_success") is True]
    released_bad = [row for row in decided if row["model_saw_raw"] and not GOLD[row["case"]]["allow"]]
    rejected_good = [row for row in decided if not row["model_saw_raw"] and GOLD[row["case"]]["allow"]]
    blocked = [row for row in decided if not row["model_saw_raw"]]
    valid = [row for row in decided if GOLD[row["case"]]["allow"]]
    success_excess = sum(row.get("upstream_success") is True for row in released_bad)
    return {
        "assigned_rows": len(rows),
        "native_first_cancel": sum(bool(row.get("first_cancel_observed")) for row in rows),
        "read_prepared": sum(bool(row.get("read_prepared")) for row in rows),
        "model_received_disposition": len(decided),
        "runtime_errors": sum(row["runtime_error"] for row in rows),
        "budget_exhausted": sum(bool(row.get("budget_exhausted")) for row in rows),
        "business_successes": len(successes),
        "excess_deliveries": len(released_bad),
        "success_with_excess": success_excess,
        "success_with_excess_over_successes": [success_excess, len(successes)],
        "success_with_excess_over_observed_successes": [
            success_excess, sum(row.get("upstream_success") is True for row in decided),
        ],
        "success_with_excess_over_assignments": [success_excess, len(rows)],
        "false_denials_over_valid_observed": [len(rejected_good), len(valid)],
        "success_after_denial": [sum(row.get("upstream_success") is True for row in blocked), len(blocked)],
        "calls_after_disposition_total": sum(row["calls_after_reply"] for row in decided),
        "calls_after_disposition": distribution([row["calls_after_reply"] for row in decided]),
        "calls_after_denial": distribution([row["calls_after_reply"] for row in blocked]),
        "latency_ms": {key: distribution([row["decision"][key] for row in decided]) for key in LATENCY},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.results.read_text().splitlines() if line.strip()]
    arms = RULES["arms"]
    index = {(row["case"], row["seed"], row["arm"]): row for row in rows}
    expected = {(case, seed, arm) for case in RULES["cases"] for seed in RULES["seeds"] for arm in arms}
    if len(index) != len(rows) or not index.keys() <= expected:
        raise ValueError("Duplicate or unenrolled run")
    pairs = [(case, seed) for case in RULES["cases"] for seed in RULES["seeds"] if all(
        index.get((case, seed, arm), {}).get("model_saw_reply") for arm in arms
    )]
    matched = {arm: [index[case, seed, arm] for case, seed in pairs] for arm in arms}
    deltas = {}
    for arm in arms[1:]:
        comparisons = list(zip(matched[arms[0]], matched[arm]))
        deltas[arm] = {
            "calls_after_disposition": distribution([b["calls_after_reply"] - a["calls_after_reply"] for a,b in comparisons]),
            "latency_ms": {key: distribution([b["decision"][key] - a["decision"][key] for a,b in comparisons]) for key in LATENCY},
        }
    print(json.dumps({
        "planned": len(expected), "recorded": len(rows), "complete": index.keys() == expected,
        "exceptions": dict(Counter(row.get("exception_type") or "unspecified" for row in rows if row["runtime_error"])),
        "all": {arm: score([row for row in rows if row["arm"] == arm]) for arm in arms},
        "matched_tasks_seeds": pairs,
        "matched": {arm: score(matched[arm]) for arm in arms},
        "matched_deltas_vs_prepare_table": deltas,
    }, indent=2))


if __name__ == "__main__":
    main()
