"""Compare round 5 with a route gate against the frozen round 6 preferences."""

import argparse
import json
import random
from pathlib import Path

from round2 import REQUIREMENTS, local_model, run_case, summarize
from round3 import paired_results
from round4 import compatible_parser
from round5 import MODE as BASELINE, retry_when_ready
from round6 import GuardedBackend, load_orders

MODE = "state_guard_with_route_check"

# Declarative priorities for the twelve frozen pairs of paraphrases.
# Routes in the same tier are equally preferred.
PRIORITIES = {
    101: (("retry",), ("change",), ("pickup",)),
    103: (("pickup",), ("retry",), ("change",)),
    105: (("pickup",), ("change",), ("retry",)),
    107: (("pickup",), ("retry",)),
    109: (("change",),),
    111: (("retry", "change"),),
    113: (("pickup",), ("retry",), ("change",)),
    115: (("pickup",), ("retry",), ("change",)),
    117: (("retry",), ("change",), ("pickup",)),
    119: (("change",), ("retry",), ("pickup",)),
    121: (("pickup",), ("change",)),
    123: (("pickup",), ("change",)),
}


def preferred_available_routes(case):
    allowed = set(case.available) & set(case.permitted)
    pair_start = case.number - (case.number - 101) % 2
    for tier in PRIORITIES[pair_start]:
        if eligible := tuple(route for route in tier if route in allowed):
            return eligible
    return ()


class RouteCheckedBackend(GuardedBackend):
    eligible_routes_for = staticmethod(preferred_available_routes)

    def __init__(self, case, mode):
        super().__init__(case, mode)
        self.guidance_sent = False
        self.eligible_routes = self.eligible_routes_for(case)

    def call(self, name, args):
        if (name == "prepare_route" and self.checked and not self.completed
                and args.get("route") not in self.eligible_routes):
            route = args.get("route")
            if route not in self.case.available:
                error = "Route unavailable."
            elif route not in self.case.permitted:
                error = "Route does not meet the customer's authorization."
            else:
                error = "Route does not match the customer's priority."
            output = {"error": error}
            if not self.guidance_sent:
                output.update({
                    "eligible_routes": list(self.eligible_routes),
                    "guidance": "Choose an eligible route and call prepare_route. "
                                "Then use its required field to complete the operation.",
                })
                self.guidance_sent = True
            return output
        return super().call(name, args)


def rollup(rows):
    result = summarize(rows)
    result["excess_relative_to_expected_route"] = sum(
        bool(set(row["seen"]) - {REQUIREMENTS[route] for route in row["expected"]})
        for row in rows
    )
    result["total_calls"] = sum(row["calls"] for row in rows)
    result["total_model_turns"] = sum(row["turns"] for row in rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--round6-trace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    orders = load_orders(args.orders)
    random.Random(61024).shuffle(orders)
    baseline = {row["case"]: row for line in args.round6_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == BASELINE}
    if set(baseline) != {order.number for order in orders}:
        raise ValueError("Round 6 baseline must match the frozen order set.")
    for order in orders:
        row = baseline[order.number]
        if (row["expected"] != sorted(order.expected) or row["user"] != order.user
                or row["available"] != list(order.available)
                or row["permitted"] != list(order.permitted)):
            raise ValueError(f"Round 6 baseline mismatch for order {order.number}.")

    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for order in orders:
            row = run_case(order, MODE, infer, backend_type=RouteCheckedBackend,
                           call_parser=compatible_parser, retry_prompt=retry_when_ready)
            row["scenario"] = order.scenario
            row["permitted"] = list(order.permitted)
            row["route_feedback_turns"] = [
                event["turn"] for event in row["events"]
                if event["call"]["name"] == "prepare_route" and "eligible_routes" in event["response"]
            ]
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(order.number, row["success"], row["completed"], row["calls"],
                  row["route_feedback_turns"], flush=True)
    result = {
        "round5": rollup(list(baseline.values())),
        "round7": rollup(rows),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
        "route_feedback_cases": [row["case"] for row in rows if row["route_feedback_turns"]],
    }
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
