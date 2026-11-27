"""Summarize completed assignments without treating missing fields as zero."""
import json
from itertools import combinations
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLANNED = {
    "qwen4-pilot": 18,
    "local-preflight": 4,
    "qwen4-full-coverage": 480,
}


def counts(rows):
    scored = [row for row in rows if not row.get("runtime_error")]
    switched = [row for row in scored if row.get("observed_events", 0) > 0]
    field_scored = [row for row in switched if row.get("stale_fields") is not None]
    denied = [row for row in switched if row.get("denials", 0) > 0]
    return {
        "recorded": len(rows),
        "runtime_errors": len(rows) - len(scored),
        "cases_recorded": len({row["case"] for row in rows}),
        "upstream_pass": sum(row["upstream_success"] is True for row in scored),
        "any_authored_event": len(switched),
        "all_authored_events": sum(row["observed_events"] == row["expected_events"] for row in switched),
        "field_scored_runs": len(field_scored),
        "stale_fields": sum(row["stale_fields"] for row in field_scored) if field_scored else None,
        "tool_calls": sum(row["tool_calls"] for row in scored),
        "post_switch_calls": sum(row["post_switch_calls"] for row in switched) if switched else None,
        "denied_runs": len(denied),
        "after_first_denial_calls": sum(row["after_first_denial"] for row in denied) if denied else None,
        "http_statuses": dict(sum((Counter(row.get("http_statuses", {})) for row in rows), Counter())),
    }


def read_rows(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines(keepends=True):
        if not line.endswith("\n"):
            break
        rows.append(json.loads(line))
    keys = {(row["case"], row["arm"], row["seed"]) for row in rows}
    if len(keys) != len(rows):
        raise ValueError(f"Duplicate run keys in {path.name}")
    return rows


def report():
    data = {}
    for name, planned in PLANNED.items():
        rows = read_rows(HERE / f"{name}.jsonl")
        arms = sorted({row["arm"] for row in rows})
        data[name] = {
            "planned": planned,
            **counts(rows),
            "by_arm": {arm: counts([row for row in rows if row["arm"] == arm]) for arm in arms},
        }
        if name == "qwen4-full-coverage":
            data[name]["by_seed"] = {
                str(seed): counts([row for row in rows if row["seed"] == seed])
                for seed in (19, 113, 421)
            }
            repeats = Counter(row["case"] for row in rows)
            data[name]["cases_with_three_repeats"] = sum(count == 3 for count in repeats.values())
            data[name]["cases_with_any_success"] = len({
                row["case"] for row in rows if row.get("upstream_success") is True
            })
            data[name]["cases_with_any_event"] = len({
                row["case"] for row in rows if row.get("observed_events", 0) > 0
            })
            successes = Counter(
                row["case"] for row in rows if row.get("upstream_success") is True
            )
            data[name]["cases_with_three_successes"] = sum(count == 3 for count in successes.values())
        if name == "qwen4-pilot":
            grouped = {}
            for row in rows:
                grouped.setdefault((row["case"], row["seed"]), {})[row["arm"]] = row
            data[name]["matched_all_arms_switched"] = sum(
                len(group) == 3 and all(
                    not r.get("runtime_error") and r.get("observed_events", 0) > 0
                    for r in group.values()
                )
                for group in grouped.values()
            )
            data[name]["matched_pairs"] = {
                f"{right}_minus_{left}": [
                    {
                        "case": case,
                        "seed": seed,
                        "stale_fields_delta": group[right]["stale_fields"] - group[left]["stale_fields"],
                        "post_switch_calls_delta": group[right]["post_switch_calls"] - group[left]["post_switch_calls"],
                    }
                    for (case, seed), group in sorted(grouped.items())
                    if all(
                        arm in group and not group[arm].get("runtime_error")
                        and group[arm].get("stale_fields") is not None
                        for arm in (left, right)
                    )
                ]
                for left, right in combinations(("agent", "table", "contract"), 2)
            }
    originals = read_rows(HERE / "qwen4-full-coverage.jsonl")
    retries = read_rows(HERE / "qwen4-transport-retry.jsonl")
    if retries:
        def key(row):
            return row["case"], row["arm"], row["seed"]

        retry_lookup = {key(row): row for row in retries}
        if not retry_lookup.keys() <= {key(row) for row in originals if row.get("runtime_error")}:
            raise ValueError("Unexpected transport retry key")
        resolved = [
            retry_lookup[key(row)]
            if key(row) in retry_lookup and not retry_lookup[key(row)].get("runtime_error")
            else row
            for row in originals
        ]
        data["qwen4-full-coverage"]["transport_retries"] = counts(retries)
        data["qwen4-full-coverage"]["after_transport_retry"] = {
            **counts(resolved),
            "by_seed": {
                str(seed): counts([row for row in resolved if row["seed"] == seed])
                for seed in (19, 113, 421)
            },
            "cases_with_any_success": len({
                row["case"] for row in resolved if row.get("upstream_success") is True
            }),
            "cases_with_any_event": len({
                row["case"] for row in resolved if row.get("observed_events", 0) > 0
            }),
        }
    return data


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
