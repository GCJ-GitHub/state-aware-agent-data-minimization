"""Extract route policy from user text, then run the unchanged guarded workflow."""

import argparse
import json
import random
import re
from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter

from round2 import REQUIREMENTS, local_model, run_case
from round3 import paired_results
from round4 import compatible_parser
from round5 import retry_when_ready
from round7 import rollup
from round8 import retry_before_route
from round9 import MODE as HUMAN, MissingPostalBackend
from round10 import OPERATORS, load_frozen_orders

MODE = "extracted_policy"
SYSTEM = """Translate the customer's logistics instructions into a JSON policy.
Routes: retry = 原址重派; pickup = 自提; change = 使用备用地址.
Return exactly one JSON object with keys rules and priority.
Rules maps each authorized route to a list of conditions that must all hold.
Use [] for a route allowed without conditions. Omit prohibited or unmentioned routes.
Each condition is ["fact_key","eq|lte|gte",literal]. Use only the listed fact keys.
Numbers use their original units. Time is an integer hour on the same day:
for example, before 14:00 means lte 13 and no later than 14:00 means lte 14.
Boolean conditions use true or false. Do not assume a fact's current value.
Priority is an ordered array of tiers, highest first. Routes in a tier are equally
preferred. Include each authorized route exactly once, including conditional and fallback routes.
Example with a different fact: 'If the pickup wait is at most 10 minutes, prefer pickup;
otherwise retry at the original address. Do not change address.'
{"rules":{"pickup":[["pickup_wait_minutes","lte",10]],"retry":[]},"priority":[["pickup"],["retry"]]}"""


def unique_keys(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Repeated JSON key.")
    return fields


def parse_policy(raw, facts):
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", raw, re.S)
    policy = json.loads(fenced[1] if fenced else raw, object_pairs_hook=unique_keys)
    if not isinstance(policy, dict) or set(policy) != {"rules", "priority"}:
        raise ValueError("Expected rules and priority.")
    rules = policy["rules"]
    if not isinstance(rules, dict) or not rules or not set(rules) <= set(REQUIREMENTS):
        raise ValueError("Invalid rule routes.")
    for conditions in rules.values():
        if not isinstance(conditions, list):
            raise ValueError("Conditions must be a list.")
        for condition in conditions:
            if not isinstance(condition, list) or len(condition) != 3:
                raise ValueError("Expected a fact, comparison and literal.")
            key, comparison, limit = condition
            if (not isinstance(key, str) or key not in facts or not isinstance(comparison, str)
                    or comparison not in OPERATORS or type(limit) is not type(facts[key])
                    or (isinstance(limit, bool) and comparison != "eq")):
                raise ValueError("Unknown fact, invalid comparison or incompatible literal.")
    priority = policy["priority"]
    if (not isinstance(priority, list) or any(
            not isinstance(tier, list) or not tier or any(not isinstance(r, str) for r in tier)
            for tier in priority)):
        raise ValueError("Invalid priority tiers.")
    ranked = [route for tier in priority for route in tier]
    if len(ranked) != len(rules) or set(ranked) != set(rules):
        raise ValueError("Every authorized route must appear exactly once in priority.")
    return policy


def extract(case, infer):
    fields = {key: type(value).__name__ for key, value in case.facts.items()}
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Customer: {case.user}\nFact schema: {json.dumps(fields)}"},
    ]
    started = perf_counter()
    raw = infer(messages, tool_schemas=None, max_tokens=256)
    latency_ms = round((perf_counter() - started) * 1000, 2)
    try:
        return raw, parse_policy(raw, case.facts), None, latency_ms
    except ValueError as error:
        return raw, None, str(error), latency_ms


def apply_extracted(case, policy):
    if policy is None:
        return replace(case, permitted=(), priority=())
    rules = policy["rules"]
    permitted = tuple(route for route in case.available
                      if route in rules and all(OPERATORS[op](case.facts[key], limit)
                                                for key, op, limit in rules[route]))
    return replace(case, permitted=permitted,
                   priority=tuple(tuple(tier) for tier in policy["priority"]))


def eligible_routes(case):
    return next((tuple(route for route in tier if route in case.permitted)
                 for tier in case.priority if any(route in case.permitted for route in tier)), ())


class ExtractedGuard(MissingPostalBackend):
    eligible_routes_for = staticmethod(eligible_routes)


def normalize_rules(rules):
    return {route: sorted({tuple(condition) for condition in conditions})
            for route, conditions in rules.items()}


def normalize_priority(priority):
    return [sorted(tier) for tier in priority]


def evaluate_policy(policy, compiled, human, reference):
    return {
        "valid": policy is not None,
        "authorization_rules_match": policy is not None
        and normalize_rules(policy["rules"]) == normalize_rules(reference["rules"]),
        "priority_rules_match": policy is not None
        and normalize_priority(policy["priority"]) == normalize_priority(reference["priority"]),
        "permitted_set_match": set(compiled.permitted) == set(human.permitted),
        "eligible_set_match": set(eligible_routes(compiled)) == human.expected,
        "extra_authorized_routes": sorted(set(compiled.permitted) - set(human.permitted)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--round10-trace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    references = {row["id"]: row for row in json.loads(args.orders.read_text())}
    orders = load_frozen_orders(args.orders)
    random.Random(101024).shuffle(orders)
    baseline = {row["case"]: row for line in args.round10_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == HUMAN}
    if set(baseline) != {case.number for case in orders}:
        raise ValueError("Round 10 baseline must match the frozen order set.")
    for case in orders:
        prior = baseline[case.number]
        if (prior["user"] != case.user or prior["expected"] != sorted(case.expected)
                or prior["available"] != list(case.available) or prior["permitted"] != list(case.permitted)):
            raise ValueError(f"Round 10 baseline mismatch for {case.number}.")
    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for case in orders:
            raw, parsed, error, latency = extract(case, infer)
            compiled = apply_extracted(case, parsed)
            row = run_case(compiled, MODE, infer, backend_type=ExtractedGuard,
                           call_parser=compatible_parser, retry_prompt=retry_when_ready,
                           pre_route_retry_prompt=retry_before_route)
            checks = evaluate_policy(parsed, compiled, case, references[case.number])
            row.update(
                extraction_raw=raw, extracted_policy=parsed, extraction_error=error,
                extraction_ms=latency, total_ms=round(latency + row["duration_ms"], 2),
                checks=checks, permitted=list(compiled.permitted),
                eligible=list(eligible_routes(compiled)), human_permitted=list(case.permitted),
                completed_unauthorized=bool(row["completed"] and row["completed"] not in case.permitted),
            )
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(case.number, checks["valid"], checks["eligible_set_match"], row["success"],
                  row["calls"], row["end"], flush=True)
    checks = {key: sum(row["checks"][key] for row in rows) for key in (
        "valid", "authorization_rules_match", "priority_rules_match",
        "permitted_set_match", "eligible_set_match",
    )}
    checks["complete_rule_match"] = sum(
        row["checks"]["authorization_rules_match"] and row["checks"]["priority_rules_match"]
        for row in rows
    )
    checks["extra_authorization_cases"] = sum(bool(row["checks"]["extra_authorized_routes"]) for row in rows)
    checks["completed_unauthorized"] = sum(row["completed_unauthorized"] for row in rows)
    summary = {
        "human_rules": rollup(list(baseline.values())),
        "extracted_rules": rollup(rows),
        "extraction": checks,
        "extra_extraction_turns": len(rows),
        "median_extraction_ms": round(median(row["extraction_ms"] for row in rows), 2),
        "median_total_ms": round(median(row["total_ms"] for row in rows), 2),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
