"""Compare a one-time missing-postal hint against round 8."""

import argparse
import json
import random
from pathlib import Path

from round2 import local_model, run_case
from round3 import paired_results
from round4 import compatible_parser
from round5 import retry_when_ready
from round6 import load_orders
from round7 import RouteCheckedBackend, rollup
from round8 import MODE as BASELINE, retry_before_route

MODE = "state_guard_with_missing_postal_hint"
HINT = (
    "Pickup needs the actual postal code. You have not received it yet. "
    'Call read_details now with fields ["postal"]. After the tool returns the postal '
    "code, call execute_route for pickup using that exact code as value."
)


class MissingPostalBackend(RouteCheckedBackend):
    def __init__(self, case, mode):
        super().__init__(case, mode)
        self.postal_hint_sent = False

    def call(self, name, args):
        output = super().call(name, args)
        if (name == "execute_route" and self.route == args.get("route") == "pickup"
                and output.get("error") == "Incorrect value."
                and "postal" not in self.delivered_fields and not self.postal_hint_sent):
            output["missing_postal_guidance"] = HINT
            self.postal_hint_sent = True
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--round8-trace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    orders = load_orders(args.orders)
    random.Random(61024).shuffle(orders)
    baseline = {row["case"]: row for line in args.round8_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == BASELINE}
    if set(baseline) != {order.number for order in orders}:
        raise ValueError("Round 8 baseline must match the frozen order set.")
    for order in orders:
        prior = baseline[order.number]
        if (prior["user"] != order.user or prior["expected"] != sorted(order.expected)
                or prior["available"] != list(order.available)
                or prior["permitted"] != list(order.permitted)):
            raise ValueError(f"Round 8 baseline mismatch for order {order.number}.")

    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for order in orders:
            row = run_case(order, MODE, infer, backend_type=MissingPostalBackend,
                           call_parser=compatible_parser, retry_prompt=retry_when_ready,
                           pre_route_retry_prompt=retry_before_route)
            row["scenario"] = order.scenario
            row["permitted"] = list(order.permitted)
            row["missing_postal_feedback_turns"] = [
                event["turn"] for event in row["events"]
                if "missing_postal_guidance" in event["response"]
            ]
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(order.number, row["success"], row["completed"], row["calls"],
                  row["missing_postal_feedback_turns"], flush=True)
    result = {
        "round8": rollup(list(baseline.values())),
        "round9": rollup(rows),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
        "missing_postal_feedback_cases": [
            row["case"] for row in rows if row["missing_postal_feedback_turns"]
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
