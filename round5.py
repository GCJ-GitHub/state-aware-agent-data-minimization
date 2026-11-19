"""Rerun the guarded workflow with one format-retry prompt when ready to execute."""

import argparse
import json
from pathlib import Path

from round2 import REQUIREMENTS, local_model, run_case, summarize
from round3 import FeedbackBackend, load_cases, paired_results
from round4 import MODE as BASELINE_MODE, compatible_parser

MODE = "state_guard_feedback_format_retry"
PROMPT = (
    "Your previous response did not contain a complete tool call. The route is prepared "
    "and you already have the required value. Complete the operation now: emit exactly "
    "one tool call using the tool schema, with the tool name in \"name\" and all required "
    "parameters in \"arguments\". Use the actual value you already received. Send the "
    "tool call, without a summary."
)


def retry_when_ready(backend, events):
    if not backend.checked or backend.route not in REQUIREMENTS or backend.completed:
        return None
    required = REQUIREMENTS[backend.route]
    available = any(event["observed_by_model"] and required in event["response"]
                    for event in events)
    return PROMPT if available else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--round2-trace", type=Path, required=True)
    parser.add_argument("--round4-trace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = load_cases(args.round2_trace)
    baseline = {row["case"]: row for line in args.round4_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == BASELINE_MODE}
    if set(baseline) != {case.number for case in cases}:
        raise ValueError("Round 4 runs must match the round 2 orders.")

    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for case in cases:
            row = run_case(case, MODE, infer, backend_type=FeedbackBackend,
                           call_parser=compatible_parser, retry_prompt=retry_when_ready)
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(case.number, row["success"], row["calls"], row["retry_turns"],
                  row["excess"], flush=True)
    summary = {
        "round4": summarize(list(baseline.values())),
        "round5": summarize(rows),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
        "model_turn_delta": sum(row["turns"] - baseline[row["case"]]["turns"] for row in rows),
        "cases_with_retry": [row["case"] for row in rows if row["retry_turns"]],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
