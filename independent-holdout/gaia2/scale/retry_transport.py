"""Retry failed infrastructure assignments and preserve the first-attempt records."""
import argparse
import json
import logging
import os
from pathlib import Path

from run import preflight, read_cases, run_episode


def key(row):
    return row["case"], row["arm"], row["seed"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    originals = [json.loads(line) for line in args.original.read_text().splitlines()]
    if len({key(row) for row in originals}) != len(originals):
        raise ValueError("Duplicate assignments in first-pass results")
    cases = read_cases(args.parquet)
    gateway = preflight.Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])
    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        seen = {key(json.loads(line)) for line in output}
        for original in originals:
            if not original.get("runtime_error") or key(original) in seen:
                continue
            case_id, arm, seed = key(original)
            row = {
                "case": case_id, "arm": arm, "seed": seed,
                **run_episode(cases[case_id], arm, seed, gateway),
            }
            output.write(json.dumps(row) + "\n")
            print({k: v for k, v in row.items() if k != "tool_trace"}, flush=True)


if __name__ == "__main__":
    main()
