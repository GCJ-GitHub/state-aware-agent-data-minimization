"""Compare guarded tool responses with and without recovery guidance."""

import argparse
import json
from pathlib import Path

from round2 import Backend, Case, FIELDS, REQUIREMENTS, local_model, run_case, summarize

CONTROL = "state_guard"
TREATMENT = "state_guard_feedback"


class FeedbackBackend(Backend):
    def __init__(self, case, mode):
        super().__init__(case, CONTROL)
        self.delivered_fields = set()

    def call(self, name, args):
        output = super().call(name, args)
        self.delivered_fields.update(set(FIELDS).intersection(output))
        if name == "get_status" and "tracking" in output:
            self.delivered_fields.add("tracking")
        if name != "read_details" or "unavailable_fields" not in output:
            return output

        if not self.checked:
            next_step = "Call get_status to get the tracking number and available routes."
        elif not self.route:
            next_step = "Choose an available route and call prepare_route."
        else:
            field = REQUIREMENTS[self.route]
            if field == "tracking":
                next_step = (
                    f"Call execute_route now with route {self.route} and value "
                    f"{self.case.values['tracking']} from get_status."
                )
            elif field in self.delivered_fields:
                next_step = (
                    f"Call execute_route now with route {self.route} and the {field} value "
                    "you received from read_details."
                )
            else:
                next_step = f"Call read_details with fields containing only {field}."
        output["guidance"] = {
            "reason": "The unavailable fields are unnecessary for this step. Continue with the required data.",
            "already_available": sorted(self.delivered_fields),
            "next_step": next_step,
        }
        return output


def load_cases(trace_path):
    cases = []
    for line in trace_path.read_text().splitlines():
        row = json.loads(line)
        if row["mode"] == CONTROL:
            case = Case(row["case"], tuple(row["available"]), row["preferred"])
            if row["user"] != case.user or row["expected"] != sorted(case.expected):
                raise ValueError(f"Round 2 case {case.number} does not match.")
            cases.append(case)
    if len(cases) != 24 or len({case.number for case in cases}) != len(cases):
        raise ValueError("Expected exactly 24 distinct round 2 orders.")
    return cases


def paired_results(pairs):
    recovered, regressed = [], []
    call_deltas = []
    for control, treatment in pairs:
        if not control["success"] and treatment["success"]:
            recovered.append(control["case"])
        if control["success"] and not treatment["success"]:
            regressed.append(control["case"])
        call_deltas.append(treatment["calls"] - control["calls"])
    return {
        "recovered_cases": recovered, "regressed_cases": regressed,
        "cases_with_more_calls": sum(delta > 0 for delta in call_deltas),
        "cases_with_fewer_calls": sum(delta < 0 for delta in call_deltas),
        "cases_with_same_calls": sum(delta == 0 for delta in call_deltas),
        "total_call_delta": sum(call_deltas),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--round2-trace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = load_cases(args.round2_trace)
    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    pairs = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for index, case in enumerate(cases):
            comparison = [(CONTROL, Backend), (TREATMENT, FeedbackBackend)]
            if index % 2:
                comparison.reverse()
            results = {}
            for mode, backend_type in comparison:
                row = run_case(case, mode, infer, backend_type=backend_type)
                results[mode] = row
                print(case.number, mode, row["success"], row["calls"], row["excess"], flush=True)
                trace.write(json.dumps(row, ensure_ascii=False) + "\n")
                trace.flush()
            pairs.append((results[CONTROL], results[TREATMENT]))

    summary = {mode: summarize([pair[index] for pair in pairs])
               for index, mode in enumerate((CONTROL, TREATMENT))}
    summary["paired"] = paired_results(pairs)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
