"""Evaluate both collection policies on frozen orders with compound preferences."""
import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from round2 import Backend, Case, local_model, run_case, summarize
from round3 import FeedbackBackend, paired_results
from round4 import compatible_parser
from round5 import MODE, retry_when_ready

BASELINE = "agent_only"


@dataclass(frozen=True)
class NewOrder(Case):
    request: str
    facts: dict
    permitted: tuple
    target: tuple
    scenario: str

    @property
    def user(self):
        return self.request

    @property
    def expected(self):
        return set(self.target)


def add_route_constraints(backend, name, args, output):
    if name == "get_status" and "status" in output and backend.case.facts:
        output["route_facts"] = backend.case.facts
    return output


def violates_consent(backend, name, args):
    return (backend.checked and not backend.completed and name == "prepare_route"
            and args.get("route") in backend.case.available
            and args.get("route") not in backend.case.permitted)


class BaselineBackend(Backend):
    def call(self, name, args):
        if violates_consent(self, name, args):
            return {"error": "Route does not meet the customer's authorization."}
        return add_route_constraints(self, name, args, super().call(name, args))


class GuardedBackend(FeedbackBackend):
    def call(self, name, args):
        if violates_consent(self, name, args):
            return {"error": "Route does not meet the customer's authorization."}
        return add_route_constraints(self, name, args, super().call(name, args))


def load_orders(path):
    orders = [NewOrder(
        number=row["id"], available=tuple(row["available"]), preferred=None,
        request=row["request"], facts=row["facts"], permitted=tuple(row["permitted"]),
        target=tuple(row["target"]), scenario=row["scenario"],
    ) for row in json.loads(path.read_text())]
    if len(orders) != 24 or len({order.number for order in orders}) != 24:
        raise ValueError("Expected 24 distinct frozen orders.")
    for order in orders:
        if not order.target or not set(order.target) <= set(order.permitted) <= set(order.available):
            raise ValueError(f"Inconsistent route oracle for order {order.number}.")
    return orders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    orders = load_orders(args.orders)
    random.Random(61024).shuffle(orders)
    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for index, order in enumerate(orders):
            variants = [(BASELINE, BaselineBackend, None),
                        (MODE, GuardedBackend, retry_when_ready)]
            if index % 2:
                variants.reverse()
            results = {}
            for mode, backend_type, retry in variants:
                row = run_case(order, mode, infer, backend_type=backend_type,
                               call_parser=compatible_parser, retry_prompt=retry)
                row["scenario"] = order.scenario
                row["permitted"] = list(order.permitted)
                results[mode] = row
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
                print(order.number, mode, row["success"], row["completed"],
                      row["excess"], row["calls"], flush=True)
            pairs.append((results[BASELINE], results[MODE]))

    summary = {}
    for index, mode in enumerate((BASELINE, MODE)):
        rows = [pair[index] for pair in pairs]
        summary[mode] = summarize(rows)
        summary[mode]["total_calls"] = sum(row["calls"] for row in rows)
        summary[mode]["total_model_turns"] = sum(row["turns"] for row in rows)
        summary[mode]["retry_cases"] = [row["case"] for row in rows if row.get("retry_turns")]
        summary[mode]["by_scenario"] = {
            scenario: summarize([row for row in rows if row["scenario"] == scenario])
            for scenario in sorted({order.scenario for order in orders})
        }
    summary["paired"] = paired_results(pairs)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
