"""Place one held catalog reply across the original Gaia2 cancellation."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "protocol.json").read_text())
source = HERE.parent / "scale" / "run.py"
spec = importlib.util.spec_from_file_location("gaia_scale", source)
scale = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scale
spec.loader.exec_module(scale)
core = scale.core

RECEIPT = "Pending catalog read result:"
DENIAL = "Pending catalog read denied:"


@dataclass(frozen=True)
class Pending:
    epoch: int
    value: str


def delivery_text(pending, current_epoch, arm):
    if arm == "contract" and pending.epoch != current_epoch:
        return f"{DENIAL} {SPEC['denial_feedback']}"
    return f"{RECEIPT} product_id={pending.value}"


class DeliveryTrace(scale.ReachabilityTrace):
    def __init__(self, case, arm, env):
        super().__init__(case, arm, env)
        self.pending = None
        self.cancel_epoch = None
        self.reply_prepared = False
        self.delivery_denied = None

    def epoch(self):
        return sum(
            event.event_type == core.EventType.ENV and event.app_name() == "Shopping"
            and event.function_name() == "cancel_order" and not event.failed()
            for event in self.env.event_log.list_view()
        )

    def start_probe(self):
        if self.pending is not None or self.epoch():
            return
        shopping = self.env.get_app("Shopping")
        product = next(
            (product for product in shopping.products.values() if product.name == self.case["product"]),
            None,
        )
        if product is None or not set(product.variants) & shopping.cart.keys():
            return
        self.pending = Pending(self.epoch(), product.product_id)

    def call(self, tool, *args, **kwargs):
        if tool.name == "Shopping__checkout":
            self.start_probe()
        result = super().call(tool, *args, **kwargs)
        if (
            tool.name != "AgentUserInterface__send_message_to_user"
            or self.pending is None or self.reply_prepared
        ):
            return result
        deadline = time.monotonic() + 90
        while not self.epoch() and time.monotonic() < deadline:
            if self.env.state.name in {"STOPPED", "FAILED"} or self.env.stop_event.is_set():
                return result
            time.sleep(0.1)
        if not self.epoch():
            return result
        self.cancel_epoch = self.epoch()
        self.reply_prepared = True
        text = delivery_text(self.pending, self.cancel_epoch, self.arm)
        self.delivery_denied = text.startswith(DENIAL)
        return text if result is None else f"{result}\n{text}"


class DeliveryBuilder(scale.TraceBuilder):
    def build(self, agent_config, env=None, mock_responses=None):
        agent = super().build(agent_config, env, mock_responses)
        self.release = DeliveryTrace(self.case, self.arm, env)
        return agent


class ReportedModel(scale.preflight.MaaSModel):
    visible_result = False
    visible_denial = False

    def chat_completion(self, messages, stop_sequences=(), **kwargs):
        seen_result = any(RECEIPT in message["content"] for message in messages if isinstance(message["content"], str))
        seen_denial = any(DENIAL in message["content"] for message in messages if isinstance(message["content"], str))
        result = super().chat_completion(messages, stop_sequences, **kwargs)
        self.visible_result |= seen_result
        self.visible_denial |= seen_denial
        return result


def run_one(case, arm, seed, gateway):
    model = ReportedModel(gateway, seed)
    judge = scale.preflight.MaaSModel(gateway, 19, judge=True)
    scenario, _, _ = core.JsonScenarioImporter().import_from_json_to_benchmark(
        case["raw"], load_completed_events=False
    )
    config = core.ScenarioRunnerConfig(agent="default", model=model.model_name, use_custom_logger=False)
    core.preprocess_scenario(
        scenario,
        judge_config=core.GraphPerEventJudgeConfig(engine=judge),
        max_scenario_duration=core.get_scenario_duration(
            scenario, config.max_time_scenario_duration, config.max_scenario_duration
        ),
    )
    builder = DeliveryBuilder(model, case, arm)
    result = core.ScenarioRunner(agent_builder=builder).run(config, scenario)
    trace = builder.release
    error = bool(model.errors or judge.errors or (result.exception is not None and not model.limit_reached))
    crossed = bool(trace and trace.pending and trace.reply_prepared)
    model_saw = model.visible_result or model.visible_denial
    post = [call for call in trace.trace if call["switch_at_entry"]] if trace else []
    return {
        "upstream_success": None if error else bool(result.success),
        "transport_or_runtime_error": error,
        "budget_exhausted": model.limit_reached,
        "started_probe": bool(trace and trace.pending),
        "old_epoch": trace.pending.epoch if trace and trace.pending else None,
        "delivery_epoch": trace.cancel_epoch if trace else None,
        "crossed_window": crossed,
        "model_saw_reply": model_saw,
        "stale_fields_to_model": int(model.visible_result) if model_saw else None,
        "model_saw_denial": model.visible_denial,
        "native_tool_calls": len(trace.trace) if trace else 0,
        "native_calls_after_switch": len(post) if crossed else None,
        "probe_count": int(bool(trace and trace.pending)),
        "agent_responses": model.calls,
        "judge_responses": judge.calls,
        "gateway_throttles": (model.attempts + judge.attempts).count(429),
        "tools": [call["tool"] for call in trace.trace] if trace else [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    cases = scale.read_cases(args.parquet)
    for case_id, product in SPEC["cases"].items():
        case = cases[case_id]
        source = json.loads(case["raw"])
        shopping = next(app["app_state"] for app in source["apps"] if app["name"] == "Shopping")
        if sum(p["name"] == product for p in shopping["products"].values()) != 1:
            raise ValueError(f"Expected one catalog match: {case_id}")
        case.update(product=product, score_fields=False)
    gateway = scale.preflight.Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])

    def execute(case_id, arm, seed):
        keys = {"case": case_id, "arm": arm, "seed": seed}
        try:
            return {**keys, **run_one(cases[case_id], arm, seed, gateway)}
        except Exception as error:
            return {**keys, "transport_or_runtime_error": True, "exception_type": type(error).__name__}

    with args.output.open("a+", buffering=1) as file:
        file.seek(0)
        seen = {(r["case"], r["arm"], r["seed"]) for r in map(json.loads, file)}
        jobs = []
        for i, case_id in enumerate(SPEC["cases"]):
            for j, seed in enumerate(SPEC["seeds"]):
                order = SPEC["arms"]
                offset = (i + j) % len(order)
                jobs.extend((case_id, arm, seed) for arm in order[offset:] + order[:offset])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute, *job) for job in jobs if job not in seen]
            for future in as_completed(futures):
                row = future.result()
                file.write(json.dumps(row) + "\n")
                print({k: v for k, v in row.items() if k != "tools"}, flush=True)


if __name__ == "__main__":
    main()
