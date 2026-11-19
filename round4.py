"""Replay round 3 orders with one narrowly scoped tool-call format extension."""

import argparse
import json
from pathlib import Path

from round2 import TOOLS, local_model, parse_calls, run_case, summarize
from round3 import FeedbackBackend, TREATMENT, load_cases, paired_results

CLOSING_TAG = "</tool_call>"
PARAMETERS = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOLS}
MODE = "state_guard_feedback_closing_tag"


def parse_closing_tag(raw, *, parameters=PARAMETERS):
    """Accept one complete tool call followed by just its closing tag."""
    candidate = raw.strip()
    if not candidate.endswith(CLOSING_TAG):
        return []
    try:
        call = json.loads(candidate.removesuffix(CLOSING_TAG))
    except json.JSONDecodeError:
        return []
    if (not isinstance(call, dict) or set(call) != {"name", "arguments"}
            or not isinstance(call["name"], str) or not isinstance(call["arguments"], dict)):
        return []
    schema = parameters.get(call["name"])
    if schema is None:
        return []
    args = call["arguments"]
    properties = schema["properties"]
    if not set(schema["required"]).issubset(args) or not set(args).issubset(properties):
        return []
    for key, value in args.items():
        if properties[key]["type"] == "string" and not isinstance(value, str):
            return []
        if properties[key]["type"] == "array" and (
            not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        ):
            return []
    return [call]


def compatible_parser(raw, *, parameters=PARAMETERS):
    calls = parse_calls(raw)
    return calls or parse_closing_tag(raw, parameters=parameters)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--round2-trace", type=Path, required=True)
    parser.add_argument("--round3-trace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = load_cases(args.round2_trace)
    baseline = {row["case"]: row for line in args.round3_trace.read_text().splitlines()
                if (row := json.loads(line))["mode"] == TREATMENT}
    if set(baseline) != {case.number for case in cases}:
        raise ValueError("Round 3 feedback runs must match the round 2 orders.")
    infer = local_model(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (args.out / "traces.jsonl").open("w") as trace:
        for case in cases:
            row = run_case(case, MODE, infer, backend_type=FeedbackBackend,
                           call_parser=compatible_parser)
            row["accepted_missing_opening_tag_turns"] = [
                turn for turn, output in enumerate(row["model_outputs"])
                if not parse_calls(output) and parse_closing_tag(output)
            ]
            rows.append(row)
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")
            trace.flush()
            print(case.number, row["success"], row["calls"], row["excess"],
                  row["accepted_missing_opening_tag_turns"], flush=True)
    summary = {
        "round3_feedback": summarize(list(baseline.values())),
        "round4_feedback": summarize(rows),
        "paired": paired_results([(baseline[row["case"]], row) for row in rows]),
        "cases_with_accepted_missing_opening_tag": [
            row["case"] for row in rows if row["accepted_missing_opening_tag_turns"]
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
