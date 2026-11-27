"""Evaluate three delivery policies over pinned Gaia2 native cancellation events."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
from threading import Event, Thread
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = json.loads((HERE / "protocol.json").read_text())
spec = importlib.util.spec_from_file_location("gaia_async_scale", HERE.parent / "scale" / "run.py")
scale = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scale
spec.loader.exec_module(scale)
core = scale.core

RELEASED = "[Pending read result]"
WITHHELD = "[Pending read denied]"
REPORT = "AgentUserInterface__send_message_to_user"
CHECKOUT = "Shopping__checkout"


@dataclass(frozen=True)
class PendingRead:
    field: str
    selector: str
    purpose: str
    value: str
    prepared_ns: int
    authorization_generation: int
    allowed_at_prepare: bool
    items: tuple[str, ...] = ()


def releases(arm, pending, current_purposes, live, generation):
    if arm == "prepare_table":
        return pending.allowed_at_prepare
    allowed = pending.purpose in current_purposes and live is not None
    if arm == "delivery_table":
        return allowed
    if arm != "narrow_contract":
        raise ValueError("Unknown arm")
    return allowed and generation == pending.authorization_generation and live == pending.value


class AsyncTrace(scale.ReachabilityTrace):
    def __init__(self, case, arm, env):
        super().__init__(case, arm, env)
        self.pending_read = None
        self.ready = Event()
        self.stop_watcher = Event()
        self.watcher = None
        self.event_seen_ns = None
        self.decision = None
        self.delivery_index = None

    def cancellation(self):
        return next(
            (e for e in self.env.event_log.list_view()
             if e.event_id == self.case["cancel_event"] and e.event_type == core.EventType.ENV
             and not e.failed()), None,
        )

    def watch(self):
        while not self.stop_watcher.is_set():
            if self.cancellation() is not None:
                self.event_seen_ns = time.perf_counter_ns()
                self.ready.set()
                return
            if self.env.stop_event.is_set():
                return
            self.stop_watcher.wait(SPEC["poll_seconds"])

    def close(self):
        self.stop_watcher.set()
        if self.watcher is not None:
            self.watcher.join(timeout=1)

    def prepare(self, args, kwargs):
        shopping = self.env.get_app("Shopping")
        field = self.case["field"]
        if field == "product_id":
            name = self.case["product"]
            product = next((p for p in shopping.products.values() if p.name == name), None)
            if product is None or not set(product.variants) & shopping.cart.keys():
                return None
            value, selector, items = product.product_id, name, ()
        elif field == "applied_discount_code":
            code = kwargs.get("discount_code", args[0] if args else None)
            items = tuple(sorted(shopping.cart))
            if not isinstance(code, str) or not code or not items:
                return None
            if any(code not in shopping.discount_codes.get(item, {}) for item in items):
                return None
            value, selector = code, code
        else:
            raise ValueError("Unknown field")
        return PendingRead(
            field, selector, self.case["initial_purpose"], value, time.perf_counter_ns(),
            SPEC["authorization_generation"], self.cancellation() is None, items,
        )

    def live_value(self, pending):
        shopping = self.env.get_app("Shopping")
        if pending.field == "product_id":
            product = next((p for p in shopping.products.values() if p.name == pending.selector), None)
            return product.product_id if product is not None else None
        if all(pending.selector in shopping.discount_codes.get(item, {}) for item in pending.items):
            return pending.selector
        return None

    def wait_for_event(self):
        deadline = time.monotonic() + SPEC["report_wait_seconds"]
        while not self.ready.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.env.stop_event.is_set():
                return False
            self.ready.wait(min(remaining, 0.1))
        return True

    def call(self, tool, *args, **kwargs):
        probe = None
        if tool.name == CHECKOUT and self.pending_read is None and self.cancellation() is None:
            probe = self.prepare(args, kwargs)
        result = super().call(tool, *args, **kwargs)
        if probe is not None and isinstance(result, str) and result in self.env.get_app("Shopping").orders:
            self.pending_read = probe
            self.watcher = Thread(target=self.watch, daemon=True)
            self.watcher.start()

        if tool.name != REPORT or self.pending_read is None or self.decision is not None:
            return result
        report_done = time.perf_counter_ns()
        if not self.wait_for_event():
            return result
        pending = self.pending_read
        started = time.perf_counter_ns()
        current = self.case["post_cancel_purposes"]
        if self.arm == "prepare_table":
            live = None
        else:
            live = self.live_value(pending)
        allowed = releases(self.arm, pending, current, live, SPEC["authorization_generation"])
        text = (f"{RELEASED} {pending.field}={pending.value}" if allowed
                else f"{WITHHELD} {SPEC['denial_feedback']}")
        done = time.perf_counter_ns()
        self.delivery_index = len(self.trace) - 1
        self.decision = {
            "released": allowed,
            "field": pending.field,
            "prepare_to_reply_ms": (done - pending.prepared_ns) / 1_000_000,
            "event_observed_to_reply_ms": (done - self.event_seen_ns) / 1_000_000,
            "report_hold_ms": (done - report_done) / 1_000_000,
            "decision_ms": (done - started) / 1_000_000,
        }
        return text if result is None else f"{result}\n{text}"


class AsyncBuilder(scale.TraceBuilder):
    def build(self, agent_config, env=None, mock_responses=None):
        agent = super().build(agent_config, env, mock_responses)
        self.release = AsyncTrace(self.case, self.arm, env)
        return agent


class VisibleModel(scale.preflight.MaaSModel):
    visible = None

    def chat_completion(self, messages, stop_sequences=(), **kwargs):
        visible = next((label for label in (RELEASED, WITHHELD)
                        if any(label in msg["content"] for msg in messages if isinstance(msg["content"], str))), None)
        response = super().chat_completion(messages, stop_sequences, **kwargs)
        self.visible = self.visible or visible
        return response


def run_one(case, arm, seed, gateway):
    model = VisibleModel(gateway, seed)
    judge = scale.preflight.MaaSModel(gateway, 19, judge=True)
    scenario, _, _ = core.JsonScenarioImporter().import_from_json_to_benchmark(case["raw"], load_completed_events=False)
    config = core.ScenarioRunnerConfig(agent="default", model=model.model_name, use_custom_logger=False)
    core.preprocess_scenario(
        scenario, judge_config=core.GraphPerEventJudgeConfig(engine=judge),
        max_scenario_duration=core.get_scenario_duration(
            scenario, config.max_time_scenario_duration, config.max_scenario_duration,
        ),
    )
    builder = AsyncBuilder(model, case, arm)
    try:
        result = core.ScenarioRunner(agent_builder=builder).run(config, scenario)
    finally:
        if builder.release:
            builder.release.close()
    trace = builder.release
    calls = trace.trace if trace else []
    decision = trace.decision if trace else None
    error = bool(model.errors or judge.errors or (result.exception is not None and not model.limit_reached))
    return {
        "upstream_success": None if error else bool(result.success),
        "runtime_error": error,
        "exception_type": type(result.exception).__name__ if result.exception else None,
        "budget_exhausted": model.limit_reached,
        "first_cancel_observed": bool(trace and case["cancel_event"] in trace.observed()),
        "read_prepared": bool(trace and trace.pending_read),
        "model_saw_reply": model.visible is not None,
        "model_saw_raw": model.visible == RELEASED,
        "decision": decision,
        "native_tool_calls": len(calls),
        "calls_after_reply": len(calls) - trace.delivery_index - 1 if model.visible and decision else None,
        "agent_responses": model.calls,
        "judge_responses": judge.calls,
        "http_429": (model.attempts + judge.attempts).count(429),
        "tools": [call["tool"] for call in calls],
    }


def load_cases(parquet):
    cases = scale.read_cases(parquet)
    selected = {}
    for case_id, rule in SPEC["cases"].items():
        case = cases[case_id]
        if case["score_fields"] or case_id in scale.DEV:
            raise ValueError(f"Prior field-policy task: {case_id}")
        raw = json.loads(case["raw"])
        events = [event for event in raw["events"] if event["event_id"] == rule["cancel_event"]]
        if len(events) != 1 or events[0]["event_type"] != "ENV" or events[0]["action"]["function"] != "cancel_order":
            raise ValueError(f"Missing frozen native cancellation: {case_id}")
        if "product" in rule:
            state = next(app["app_state"] for app in raw["apps"] if app["name"] == "Shopping")
            if sum(p["name"] == rule["product"] for p in state["products"].values()) != 1:
                raise ValueError(f"Missing unique frozen product: {case_id}")
        selected[case_id] = {**case, **rule, "score_fields": False}
    return selected


def verify_freeze():
    for line in (HERE / "FREEZE.sha256").read_text().splitlines():
        expected, path = line.split("  ", 1)
        with (ROOT / path).open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise ValueError(f"Frozen input changed: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    verify_freeze()
    cases = load_cases(args.parquet)
    if args.verify_only:
        print(f"Verified frozen runner and {len(cases)} upstream cases", flush=True)
        return
    if args.output is None:
        parser.error("--output is required for live runs")
    gateway = scale.preflight.Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])

    def execute(case_id, arm, seed):
        keys = {"case": case_id, "arm": arm, "seed": seed}
        print("START", keys, flush=True)
        try:
            return {**keys, **run_one(cases[case_id], arm, seed, gateway)}
        except Exception as error:
            return {**keys, "upstream_success": None, "runtime_error": True,
                    "exception_type": type(error).__name__}

    jobs = []
    for seed_index, seed in enumerate(SPEC["seeds"]):
        for index, case_id in enumerate(cases):
            arms = SPEC["arms"]
            offset = (index + seed_index) % len(arms)
            jobs.extend((case_id, arm, seed) for arm in arms[offset:] + arms[:offset])
    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        seen = {(r["case"], r["arm"], r["seed"]) for r in map(json.loads, output)}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            work = [pool.submit(execute, *job) for job in jobs if job not in seen]
            for future in as_completed(work):
                row = future.result()
                output.write(json.dumps(row) + "\n")
                print("DONE", {k: v for k, v in row.items() if k != "tools"}, flush=True)


if __name__ == "__main__":
    main()
