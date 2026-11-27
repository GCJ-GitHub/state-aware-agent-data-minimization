"""Run native Gaia2 reachability and supported field-policy comparisons."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
source = HERE.parent / "qwen4-preflight" / "run.py"
spec = importlib.util.spec_from_file_location("gaia_preflight", source)
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)
core = preflight.core
RULES = core.RULES
DEV = preflight.PROTOCOL["cases"]


class ReachabilityTrace(core.FieldRelease):
    """Observe every authored environment event for a benchmark-only case."""

    def __init__(self, case, arm, env):
        super().__init__(case, arm, env)
        self.expected = set(case["original_event_ids"])

    def observed(self):
        return {
            event.event_id
            for event in self.env.event_log.list_view()
            if event.event_type == core.EventType.ENV
            and event.event_id in self.expected
            and not event.failed()
        }

    def epoch(self):
        return len(self.observed())

    def partition(self, name, result, args, kwargs):
        if self.case.get("score_fields"):
            return super().partition(name, result, args, kwargs)
        return result, set()


class TraceBuilder(core.InstrumentedBuilder):
    def build(self, agent_config, env=None, mock_responses=None):
        agent = super().build(agent_config, env, mock_responses)
        self.release = ReachabilityTrace(self.case, self.arm, env)
        return agent


def read_cases(parquet):
    with parquet.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != RULES["dataset_sha256"]:
            raise ValueError("Unexpected Adaptability snapshot")
    cases = {}
    for batch in core.pq.ParquetFile(parquet).iter_batches(batch_size=4, columns=["id", "data"]):
        for row in batch.to_pylist():
            public_events = [
                event for event in json.loads(row["data"])["events"]
                if event["event_type"] == "ENV"
            ]
            case_id = row["id"]
            field_rule = RULES["cases"].get(case_id)
            cases[case_id] = {
                "raw": row["data"],
                "original_event_ids": [event["event_id"] for event in public_events],
                "event_actions": [
                    f"{event['action']['app']}.{event['action']['function']}" for event in public_events
                ],
                "score_fields": field_rule is not None,
                **(field_rule or {}),
            }
    if len(cases) != 160 or not (set(DEV) | RULES["cases"].keys()) <= cases.keys():
        raise ValueError("Unexpected case inventory")
    return cases


def run_episode(case, arm, seed, gateway):
    agent = preflight.MaaSModel(gateway, seed) if gateway else core.LocalModel(seed)
    judge = preflight.MaaSModel(gateway, 19, judge=True) if gateway else core.LocalModel(19, judge=True)
    scenario, _, _ = core.JsonScenarioImporter().import_from_json_to_benchmark(
        case["raw"], load_completed_events=False
    )
    config = core.ScenarioRunnerConfig(agent="default", model=agent.model_name, use_custom_logger=False)
    core.preprocess_scenario(
        scenario,
        judge_config=core.GraphPerEventJudgeConfig(engine=judge),
        max_scenario_duration=core.get_scenario_duration(
            scenario, config.max_time_scenario_duration, config.max_scenario_duration
        ),
    )
    builder = TraceBuilder(agent, case, arm)
    result = core.ScenarioRunner(agent_builder=builder).run(config, scenario)
    release = builder.release
    observed = release.observed() if release else set()
    calls = release.trace if release else []
    post = [c for c in calls if c.get("switch_at_delivery", c["switch_at_entry"])]
    denial_index = next((i for i, c in enumerate(post) if c["denied"]), None)
    error = bool(agent.errors or judge.errors or (result.exception is not None and not agent.limit_reached))
    return {
        "upstream_success": None if error else bool(result.success),
        "runtime_error": error,
        "budget_exhausted": agent.limit_reached,
        "expected_events": len(case["original_event_ids"]),
        "observed_events": len(observed),
        "score_fields": case["score_fields"],
        "stale_fields": len(release.delivered) if case["score_fields"] and observed else None,
        "tool_calls": len(calls),
        "post_switch_calls": len(post) if observed else None,
        "denials": sum(c["denied"] for c in calls),
        "after_first_denial": None if denial_index is None else len(post) - denial_index - 1,
        "agent_responses": agent.calls,
        "judge_responses": judge.calls,
        "http_statuses": dict(Counter(map(str, getattr(agent, "attempts", []) + getattr(judge, "attempts", [])))),
        "tool_trace": calls,
    }


def job_grid(mode, cases):
    if mode == "pilot":
        return [
            (case_id, arm, seed)
            for j, case_id in enumerate(RULES["cases"])
            for i, seed in enumerate(RULES["seeds"])
            for arm in RULES["arms"][(i + j) % 3:] + RULES["arms"][:(i + j) % 3]
        ]
    if mode == "local":
        return [(case_id, "agent", seed) for case_id in DEV for seed in preflight.PROTOCOL["seeds"]]
    return [(case_id, "agent", seed) for seed in RULES["seeds"] for case_id in sorted(cases)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["audit", "pilot", "local", "full-coverage"])
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", default=1, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    cases = read_cases(args.parquet)
    if args.mode == "audit":
        args.output.write_text(json.dumps({
            case_id: {k: case[k] for k in ("event_actions", "score_fields")}
            for case_id, case in cases.items()
        }, indent=2) + "\n")
        return
    gateway = None if args.mode == "local" else preflight.Gateway(
        os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"]
    )
    jobs = job_grid(args.mode, cases)

    def execute(case_id, arm, seed):
        row = {"case": case_id, "arm": arm, "seed": seed}
        try:
            return {**row, **run_episode(cases[case_id], arm, seed, gateway)}
        except Exception as err:
            return {**row, "runtime_error": True, "exception_type": type(err).__name__}

    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        done = {(r["case"], r["arm"], r["seed"]) for r in map(json.loads, output)}
        remaining = [job for job in jobs if job not in done]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute, *job) for job in remaining]
            for future in as_completed(futures):
                record = future.result()
                output.write(json.dumps(record) + "\n")
                print({k: v for k, v in record.items() if k != "tool_trace"}, flush=True)


if __name__ == "__main__":
    main()
