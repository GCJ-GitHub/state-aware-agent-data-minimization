"""Compare one early continuation prompt against round 7 on the same orders."""

import argparse
import json
import random
from pathlib import Path

from round2 import local_model, run_case
from round3 import paired_results
from round4 import compatible_parser
from round5 import retry_when_ready
from round6 import load_orders
from round7 import MODE as BASELINE, RouteCheckedBackend, rollup

MODE = "state_guard_with_early_retry"
QUERY_PROMPT = (
    "The order still needs action. Your previous response did not call a tool. "
    "Call get_status now to look up the order before choosing a route. "
    "Emit one complete tool call using the registered schema, without a summary."
)
ROUTE_PROMPT = (
    "The order still needs action. You already have the status and available routes. "
    "Use the customer's original priority order and conditions together with that status "
    "to choose the highest-priority available authorized route. "
    "Call prepare_route now for the route you choose. Emit one complete tool call using "
    "the registered schema, without a summary."
)


def retry_before_route(backend, events):
    if backend.completed or any(event["call"]["name"] == "prepare_route" for event in events):
        return None
    if backend.checked:
        return ROUTE_PROMPT if any(
            event["observed_by_model"] and event["call"]["name"] == "get_status"
            and "status" in event["response"] for event in events
        ) else None
    return QUERY_PROMPT if not any(event["call"]["name"] == "get_status" for event in events) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--round7-trace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    orders = load_orders(args.orders)
    random.Random(61024).shuffle(orders)
    baseline = {row["case"]: row for line in args.round7_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == BASELINE}
    if set(baseline) != {order.number for order in orders}:
        raise ValueError("Round 7 baseline must match the frozen order set.")
    for order in orders:
        prior = baseline[order.number]
        if (prior["user"] != order.user or prior["expected"] != sorted(order.expected)
                or prior["available"] != list(order.available)
                or prior["permitted"] != list(order.permitted)):
            raise ValueError(f"Round 7 baseline mismatch for order {order.number}.")

    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for order in orders:
            row = run_case(order, MODE, infer, backend_type=RouteCheckedBackend,
                           call_parser=compatible_parser, retry_prompt=retry_when_ready,
                           pre_route_retry_prompt=retry_before_route)
            row["scenario"] = order.scenario
            row["permitted"] = list(order.permitted)
            if row["pre_route_retry_turns"]:
                prompt_turn = row["pre_route_retry_turns"][0]
                row["pre_route_retry_stage"] = (
                    "after_status" if any(event["turn"] < prompt_turn
                                          and event["call"]["name"] == "get_status"
                                          for event in row["events"]) else "before_status"
                )
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(order.number, row["success"], row["completed"], row["calls"],
                  row.get("pre_route_retry_stage"), flush=True)
    result = {
        "round7": rollup(list(baseline.values())),
        "round8": rollup(rows),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
        "early_retry_cases": [row["case"] for row in rows if row["pre_route_retry_turns"]],
    }
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
