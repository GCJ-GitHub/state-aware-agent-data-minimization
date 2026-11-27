"""Run a field-release pilot over the unmodified Gaia2 task/event inputs."""
import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
from urllib.request import Request, urlopen

from are.simulation.agents.agent_builder import AgentBuilder
from are.simulation.agents.llm.llm_engine import LLMEngine
from are.simulation.agents.llm.litellm.litellm_engine import role_conversions
from are.simulation.data_handler.importer import JsonScenarioImporter
from are.simulation.exceptions import FatalError
from are.simulation.scenario_runner import ScenarioRunner
from are.simulation.scenarios.config import ScenarioRunnerConfig
from are.simulation.scenarios.scenario_imported_from_json.utils import (
    get_scenario_duration,
    preprocess_scenario,
)
from are.simulation.types import EventType, SimulatedGenerationTimeConfig
from are.simulation.validation.configs import GraphPerEventJudgeConfig
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
RULES = json.loads((HERE / "protocol.json").read_text())
MODEL_URL = "http://127.0.0.1:11434/api/chat"
ACTION_FORMAT = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "action_input": {"type": "object", "additionalProperties": True},
    },
    "required": ["action", "action_input"],
    "additionalProperties": False,
}


def add_action_prefix(content):
    try:
        action = json.loads(content)
    except json.JSONDecodeError:
        return content
    if (
        isinstance(action, dict)
        and set(action) == {"action", "action_input"}
        and isinstance(action["action"], str)
        and isinstance(action["action_input"], dict)
    ):
        return "Action: " + content.strip()
    return content


class LocalModel(LLMEngine):
    def __init__(self, seed, judge=False):
        super().__init__(RULES["model"])
        self.seed = seed
        self.judge = judge
        self.calls = 0
        self.limit_reached = False
        self.errors = 0

    def chat_completion(self, messages, stop_sequences=(), **kwargs):
        if not self.judge and self.calls >= RULES["max_agent_model_responses_per_episode"]:
            self.limit_reached = True
            raise FatalError("Frozen model response budget exhausted")
        self.calls += 1
        options = {
            "temperature": 0 if self.judge else 0.3,
            "seed": self.seed + (0 if self.judge else self.calls - 1),
            "num_ctx": RULES["context_tokens"],
            "num_predict": RULES["judge_max_tokens" if self.judge else "agent_max_tokens"],
            "stop": list(stop_sequences),
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": role_conversions.get(m["role"], m["role"]), "content": m["content"]}
                for m in messages
            ],
            "think": False,
            "stream": False,
            "options": options,
            "keep_alive": "30m",
        }
        if not self.judge:
            payload["format"] = ACTION_FORMAT
            payload["messages"][0]["content"] += (
                "\nReply with exactly one JSON object containing action and action_input."
            )
        request = Request(
            MODEL_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=180) as response:
                answer = json.load(response)
        except Exception:
            self.errors += 1
            raise
        content = answer["message"]["content"]
        if not self.judge:
            content = add_action_prefix(content)
        return content, {
            "completion_duration": RULES["simulated_seconds_per_model_response"],
        }


class LocalModelBuilder:
    def __init__(self, model):
        self.model = model

    def create_engine(self, **kwargs):
        return self.model


@dataclass(frozen=True)
class ReadGrant:
    route_epoch: int
    purpose: str


class FieldRelease:
    def __init__(self, case, arm, env):
        self.case = case
        self.arm = arm
        self.env = env
        self.trace = []
        self.delivered = set()
        self.old_product = case.get("retired_product")

    def epoch(self):
        if self.env.event_log is None:
            return 0
        return sum(
            event.event_type == EventType.ENV
            and f"{event.app_name()}.{event.function_name()}" == self.case["switch"]
            and not event.failed()
            for event in self.env.event_log.list_view()
        )

    def partition(self, name, result, args, kwargs):
        """Return safe projection and identifiers of the fields it removes."""
        if self.old_product is None:
            if name == "Shopping__get_all_discount_codes" and isinstance(result, dict):
                return {}, {("coupon_code", code) for code in result}
            if name == "Shopping__get_discount_code_info" and isinstance(result, dict):
                code = kwargs.get("discount_code", args[0] if args else "")
                return {}, {("discount_percentage", code, item_id) for item_id in result}
        elif name == "Shopping__search_product" and isinstance(result, list):
            removed = [product for product in result if product.name == self.old_product]
            return (
                [product for product in result if product.name != self.old_product],
                {field for product in removed for field in self.product_fields(product)},
            )
        elif name == "Shopping__get_product_details" and getattr(result, "name", None) == self.old_product:
            return None, self.product_fields(result)
        elif name == "Shopping__list_all_products" and isinstance(result, dict):
            products = result.get("products", {})
            if self.old_product in products:
                return (
                    {**result, "products": {k: v for k, v in products.items() if k != self.old_product}},
                    {("product_id", products[self.old_product])},
                )
        return result, set()

    @staticmethod
    def product_fields(product):
        fields = {("product_id", product.product_id)}
        for variant in product.variants.values():
            for name in ("item_id", "price", "available"):
                fields.add((name, variant.item_id))
            fields.update(("option", variant.item_id, option) for option in variant.options)
        return fields

    def call(self, tool, *args, **kwargs):
        before = self.epoch()
        grant = ReadGrant(before, "replacement" if before else "initial_order")
        record = {"tool": tool.name, "switch_at_entry": bool(before), "denied": False}
        self.trace.append(record)
        result = tool(*args, **kwargs)
        after = self.epoch()
        record["switch_at_delivery"] = bool(after)
        safe, fields = self.partition(tool.name, result, args, kwargs)
        if not fields:
            return result
        if self.arm == "table":
            obsolete = bool(before)
        elif self.arm == "contract":
            obsolete = grant.purpose == "replacement" or grant.route_epoch != after
        else:
            obsolete = False
        if obsolete:
            record["denied"] = True
            if not safe:
                return RULES["recovery_feedback"]
            return safe
        if after:
            self.delivered.update(fields)
            record["stale_fields"] = len(fields)
        return result


class InstrumentedBuilder(AgentBuilder):
    def __init__(self, model, case, arm):
        super().__init__(LocalModelBuilder(model))
        self.case = case
        self.arm = arm
        self.release = None

    def build(self, agent_config, env=None, mock_responses=None):
        agent = super().build(agent_config, env, mock_responses)
        agent.simulated_generation_time_config = SimulatedGenerationTimeConfig(
            mode="fixed", seconds=RULES["simulated_seconds_per_model_response"]
        )
        agent.react_agent.simulated_generation_time_config = agent.simulated_generation_time_config
        init_tools = agent.init_tools
        self.release = FieldRelease(self.case, self.arm, env)

        def setup_tools(scenario):
            init_tools(scenario)
            for adapter in agent.tools:
                if hasattr(adapter, "app_tool"):
                    tool = adapter.app_tool

                    def call(*args, _tool=tool, **kwargs):
                        return self.release.call(_tool, *args, **kwargs)

                    adapter.app_tool = call

        agent.init_tools = setup_tools
        agent.react_agent.init_system_prompts["system_prompt"] += "\n\n" + RULES["agent_instruction"]
        return agent


def selected_rows(parquet):
    found = {}
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=4, columns=["id", "data"]):
        for row in batch.to_pylist():
            if row["id"] in RULES["cases"]:
                found[row["id"]] = row["data"]
    if found.keys() != RULES["cases"].keys():
        raise ValueError("Dataset does not contain all frozen case IDs")
    return found


def run_one(case_id, raw_data, arm, seed):
    scenario, _, _ = JsonScenarioImporter().import_from_json_to_benchmark(
        raw_data, load_completed_events=False
    )
    model = LocalModel(seed)
    judge = LocalModel(19, judge=True)
    config = ScenarioRunnerConfig(agent="default", model=RULES["model"], use_custom_logger=False)
    preprocess_scenario(
        scenario,
        judge_config=GraphPerEventJudgeConfig(engine=judge),
        max_scenario_duration=get_scenario_duration(
            scenario, config.max_time_scenario_duration, config.max_scenario_duration
        ),
    )
    builder = InstrumentedBuilder(model, RULES["cases"][case_id], arm)
    result = ScenarioRunner(agent_builder=builder).run(config, scenario)
    release = builder.release
    calls = [] if release is None else release.trace
    post_switch = [call for call in calls if call.get("switch_at_delivery", call["switch_at_entry"])]
    first_denial = next((i for i, call in enumerate(post_switch) if call["denied"]), None)
    runtime_failure = model.errors or judge.errors or (result.exception is not None and not model.limit_reached)
    return {
        "case": case_id,
        "arm": arm,
        "seed": seed,
        "upstream_success": None if runtime_failure else bool(result.success),
        "runtime_failure": bool(runtime_failure),
        "budget_exhausted": model.limit_reached,
        "upstream_exception_type": type(result.exception).__name__ if result.exception else None,
        "switch_observed": bool(release and release.epoch()),
        "unique_stale_fields": 0 if release is None else len(release.delivered),
        "agent_tool_calls": len(calls),
        "post_switch_tool_calls": len(post_switch),
        "denials": sum(call["denied"] for call in calls),
        "calls_after_first_denial": None if first_denial is None else len(post_switch) - first_denial - 1,
        "agent_model_calls": model.calls,
        "judge_model_calls": judge.calls,
        "tool_trace": calls,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for logger in ("httpx", "litellm", "LiteLLM"):
        logging.getLogger(logger).setLevel(logging.ERROR)
    with args.parquet.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != RULES["dataset_sha256"]:
            raise ValueError("Unexpected parquet hash")
    cases = selected_rows(args.parquet)
    completed = set()
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            result = json.loads(line)
            completed.add((result["case"], result["arm"], result["seed"]))
    with args.output.open("a", buffering=1) as output:
        for index, (case_id, case_data) in enumerate(sorted(cases.items(), reverse=True)):
            for repetition, seed in enumerate(RULES["seeds"]):
                arms = RULES["arms"]
                start = (repetition + index) % len(arms)
                for arm in arms[start:] + arms[:start]:
                    if (case_id, arm, seed) in completed:
                        continue
                    print(f"Starting {case_id[:4]} {arm} {seed}", flush=True)
                    result = run_one(case_id, case_data, arm, seed)
                    output.write(json.dumps(result) + "\n")
                    print({k: v for k, v in result.items() if k != "tool_trace"}, flush=True)


if __name__ == "__main__":
    main()
