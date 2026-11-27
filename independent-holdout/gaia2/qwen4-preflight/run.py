"""Measure reachability on Gaia2 development cases using the MaaS Qwen4-Max."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / "protocol.json").read_text())
sys.path.insert(0, str(HERE.parents[2]))
from qwen4_paper_replication import Gateway, GatewayError

spec = importlib.util.spec_from_file_location("gaia_field_release", HERE.parent / "run.py")
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)


class MaaSModel(core.LLMEngine):
    def __init__(self, gateway, seed, judge=False):
        super().__init__(PROTOCOL["model"])
        self.gateway = gateway
        self.seed = seed
        self.judge = judge
        self.calls = 0
        self.errors = 0
        self.limit_reached = False
        self.attempts = []

    def chat_completion(self, messages, stop_sequences=(), **kwargs):
        if not self.judge and self.calls >= core.RULES["max_agent_model_responses_per_episode"]:
            self.limit_reached = True
            raise core.FatalError("Development model response budget exhausted")
        self.calls += 1
        messages = [
            {"role": core.role_conversions.get(m["role"], m["role"]), "content": m["content"]}
            for m in messages
        ]
        body = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "enable_thinking": False,
            "temperature": 0 if self.judge else 0.3,
            "seed": self.seed + (0 if self.judge else self.calls - 1),
            "max_tokens": core.RULES["judge_max_tokens" if self.judge else "agent_max_tokens"],
        }
        if not self.judge:
            body["response_format"] = {"type": "json_object"}
            messages[0]["content"] += (
                "\nReply with exactly one JSON object with action (tool name) and action_input "
                "(an object of arguments). Do not add text outside the JSON."
            )
        try:
            data = self.gateway.generate(body, self.attempts)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise GatewayError("empty_completion")
        except (GatewayError, KeyError, TypeError, IndexError) as error:
            self.errors += 1
            raise core.FatalError(type(error).__name__) from None
        if not self.judge:
            content = core.add_action_prefix(content)
        return content, {
            "completion_duration": core.RULES["simulated_seconds_per_model_response"],
        }


def selected_rows(parquet):
    with parquet.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != core.RULES["dataset_sha256"]:
            raise ValueError("Unexpected dataset hash")
    case_ids = set(PROTOCOL["cases"])
    if case_ids & core.RULES["cases"].keys():
        raise ValueError("Development cases overlap formal cases")
    cases = {
        row["id"]: row["data"]
        for batch in core.pq.ParquetFile(parquet).iter_batches(batch_size=4, columns=["id", "data"])
        for row in batch.to_pylist()
        if row["id"] in case_ids
    }
    if cases.keys() != case_ids:
        raise ValueError("Missing development cases")
    return cases


def run_episode(raw, gateway, seed):
    case = {"switch": PROTOCOL["switch"]}
    scenario, _, _ = core.JsonScenarioImporter().import_from_json_to_benchmark(
        raw, load_completed_events=False
    )
    model = MaaSModel(gateway, seed)
    judge = MaaSModel(gateway, 19, judge=True)
    config = core.ScenarioRunnerConfig(agent="default", model=PROTOCOL["model"], use_custom_logger=False)
    core.preprocess_scenario(
        scenario,
        judge_config=core.GraphPerEventJudgeConfig(engine=judge),
        max_scenario_duration=core.get_scenario_duration(
            scenario, config.max_time_scenario_duration, config.max_scenario_duration
        ),
    )
    builder = core.InstrumentedBuilder(model, case, PROTOCOL["arm"])
    result = core.ScenarioRunner(agent_builder=builder).run(config, scenario)
    release = builder.release
    calls = release.trace if release else []
    reached = bool(release and release.epoch())
    error = bool(model.errors or judge.errors or (result.exception is not None and not model.limit_reached))
    return {
        "upstream_success": None if error else bool(result.success),
        "switch_observed": reached,
        "gateway_or_runtime_failure": error,
        "budget_exhausted": model.limit_reached,
        "tool_calls": len(calls),
        "post_switch_tool_calls": sum(c.get("switch_at_delivery", c["switch_at_entry"]) for c in calls),
        "agent_responses": model.calls,
        "judge_responses": judge.calls,
        "http_statuses": dict(Counter(map(str, model.attempts + judge.attempts))),
        "tool_trace": calls,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    cases = selected_rows(args.parquet)
    gateway = Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])
    key = ("case", "seed")
    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        done = {tuple(row[k] for k in key) for row in map(json.loads, output)}
        for case_id in PROTOCOL["cases"]:
            for seed in PROTOCOL["seeds"]:
                if (case_id, seed) in done:
                    continue
                print("Starting", case_id[:4], seed, flush=True)
                row = {"case": case_id, "seed": seed, **run_episode(cases[case_id], gateway, seed)}
                output.write(json.dumps(row) + "\n")
                print({k: v for k, v in row.items() if k != "tool_trace"}, flush=True)
                if row["gateway_or_runtime_failure"]:
                    break


if __name__ == "__main__":
    main()
