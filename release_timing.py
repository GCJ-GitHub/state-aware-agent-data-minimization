"""Isolate release timing using a shared policy and shared execution harness."""

import argparse
import json
import random
from functools import partial
from pathlib import Path

from airgap_comparison import CALL_PARSER, SYSTEM, TOOLS_WITH_CONFIRMATION, load_cases, summary_for
from round2 import FIELDS, REQUIREMENTS, SYSTEM as BASE_SYSTEM, local_model, run_case
from round3 import paired_results
from round5 import retry_when_ready
from round8 import retry_before_route
from round10 import ConfiguredGuard

UPFRONT = "upfront_policy_union"
ON_DEMAND = "state_gated"
EXECUTION_SYSTEM = BASE_SYSTEM.replace(
    "For tracking, use the value from get_status. For another field, get the actual\n"
    "value from read_details.",
    "For tracking, use the value from get_status. For another required field, use its actual "
    "value from Prefetched order details or any previous tool response if already present. "
    "If you already have the required value, skip read_details and execute directly. "
    "Call read_details only if the required value is missing.",
)


class SharedBackend(ConfiguredGuard):
    def __init__(self, case, mode, initial_fields):
        super().__init__(case, mode)
        self.delivered_fields.update(initial_fields)

    def call(self, name, args):
        if name == "request_confirmation" and not self.completed:
            if args.get("field") in self.needed:
                return {"approved": False, "reason": "The customer already authorized this "
                        "route's required field. Read the field without further confirmation."}
            return {"approved": False, "reason": "No additional authorization was granted for "
                    "fields outside the prepared route."}
        return super().call(name, args)


def covered_fields(cases):
    routes_by_pair = {}
    for case in cases:
        routes_by_pair.setdefault(case.pair, set()).update(case.permitted)
    return {pair: sorted({REQUIREMENTS[route] for route in routes}.intersection(FIELDS))
            for pair, routes in routes_by_pair.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--orders", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    cases = load_cases(args.orders)
    fields = covered_fields(cases)
    random.Random(221024).shuffle(cases)
    infer = partial(local_model(args.model), tool_schemas=TOOLS_WITH_CONFIRMATION)
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for index, case in enumerate(cases):
            by_mode = {}
            modes = (UPFRONT, ON_DEMAND) if index % 2 == 0 else (ON_DEMAND, UPFRONT)
            for mode in modes:
                initial = ({field: case.values[field] for field in fields[case.pair]}
                           if mode == UPFRONT else {})
                row = run_case(case, mode, infer, call_parser=CALL_PARSER,
                               backend_type=partial(SharedBackend, initial_fields=initial),
                               retry_prompt=retry_when_ready, pre_route_retry_prompt=retry_before_route,
                               extra_system=SYSTEM, initial_fields=initial, base_system=EXECUTION_SYSTEM)
                confirmations = [event for event in row["events"]
                                 if event["call"]["name"] == "request_confirmation"]
                row.update(
                    pair=case.pair, facts=case.facts, scenario=case.scenario,
                    initial_fields=sorted(initial), permitted=list(case.permitted),
                    extra_fields_vs_expected=sorted(set(row["seen"]) -
                                                    {REQUIREMENTS[r] for r in row["expected"]}),
                    confirmation_requests=len(confirmations),
                    confirmation_approvals=sum(e["response"].get("approved") is True
                                               for e in confirmations),
                    upfront_filter_inferences=0,
                )
                by_mode[mode] = row
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
                print(case.number, mode, row["success"], row["calls"],
                      row["extra_fields_vs_expected"], len(confirmations), flush=True)
            pairs.append((by_mode[UPFRONT], by_mode[ON_DEMAND]))
    result = {mode: summary_for([pair[index] for pair in pairs])
              for index, mode in enumerate((UPFRONT, ON_DEMAND))}
    result["paired"] = paired_results(pairs)
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
