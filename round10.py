"""Compare agent-controlled reads and round 9 on a frozen new order set."""

import argparse
import json
import operator
import random
from dataclasses import dataclass
from pathlib import Path

from round2 import REQUIREMENTS, local_model, run_case
from round3 import paired_results
from round4 import compatible_parser
from round5 import retry_when_ready
from round6 import BASELINE, BaselineBackend, NewOrder
from round7 import rollup
from round8 import retry_before_route
from round9 import MODE, MissingPostalBackend

OPERATORS = {"eq": operator.eq, "lte": operator.le, "gte": operator.ge}


def route_sets(case):
    return next(tuple(route for route in tier if route in case.permitted)
                for tier in case.priority if any(route in case.permitted for route in tier))


class ConfiguredGuard(MissingPostalBackend):
    eligible_routes_for = staticmethod(route_sets)



@dataclass(frozen=True)
class PolicyOrder(NewOrder):
    priority: tuple


def load_frozen_orders(path):
    cases = []
    for item in json.loads(path.read_text()):
        allowed = tuple(route for route in item["available"]
                        if route in item["rules"] and all(
                            OPERATORS[comparison](item["facts"][key], limit)
                            for key, comparison, limit in item["rules"][route]))
        case = PolicyOrder(item["id"], tuple(item["available"]), None, item["request"],
                           item["facts"], allowed, tuple(item["target"]), item["scenario"],
                           tuple(tuple(t) for t in item["priority"]))
        if not case.target or not set(case.available) <= set(REQUIREMENTS):
            raise ValueError(f"Invalid route fixture for {case.number}.")
        if set(route_sets(case)) != case.expected:
            raise ValueError(f"Policy and expected route disagree for {case.number}.")
        cases.append(case)
    if len(cases) != 24 or len({case.number for case in cases}) != 24:
        raise ValueError("Expected 24 distinct orders.")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cases = load_frozen_orders(args.orders)
    random.Random(101024).shuffle(cases)
    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for index, case in enumerate(cases):
            modes = (BASELINE, MODE) if index % 2 == 0 else (MODE, BASELINE)
            pair = {}
            for mode in modes:
                guarded = mode == MODE
                row = run_case(case, mode, infer, call_parser=compatible_parser,
                               backend_type=ConfiguredGuard if guarded else BaselineBackend,
                               retry_prompt=retry_when_ready if guarded else None,
                               pre_route_retry_prompt=retry_before_route if guarded else None)
                row.update(scenario=case.scenario, permitted=list(case.permitted))
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
                pair[mode] = row
                print(case.number, mode, row["success"], row["completed"],
                      row["calls"], row["excess"], flush=True)
            pairs.append((pair[BASELINE], pair[MODE]))
    summary = {mode: rollup([pair[index] for pair in pairs])
               for index, mode in enumerate((BASELINE, MODE))}
    summary["paired"] = paired_results(pairs)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
