"""Rerun the paper's model-dependent comparisons with frozen original adapters."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import time
from types import FunctionType

import requests

import airgap_state_study as airgap
import necessity_factorial as factorial
import necessity_holdout as three
import necessity_native_retest as native
import strong_backend_autonomous as strong

ROOT = strong.ROOT
OUT = ROOT / "qwen4-max-paper-replication"
MODEL = "qwen4-max"


@dataclass(frozen=True)
class Study:
    module: object
    mode: str
    max_tokens: int


STUDIES = {
    "strong": Study(strong, "strong", strong.CAP),
    "three-arm": Study(three, "native", native.CAP),
    "airgap": Study(airgap, "text", airgap.CAP),
    "native-factorial": Study(native, "native", native.CAP),
    "text-factorial": Study(factorial, "text", factorial.CAP),
}


class GatewayError(RuntimeError):
    pass


class Gateway(strong.Client):
    def generate(self, body, attempts):
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()
        for retry in range(16):
            self.await_slot()
            attempts.append(None)
            try:
                response = self.local.session.post(self.endpoint, json=body, timeout=(10, 70),
                                                  headers={"api-key": self.key})
                attempts[-1] = response.status_code
                if response.status_code == 429:
                    self.throttled(response)
                    continue
                if response.status_code in (400, 401, 403, 404, 422):
                    raise GatewayError(f"HTTP_{response.status_code}")
                if response.ok:
                    data = response.json()
                    if data.get("choices"):
                        self.successful()
                        return data
            except (requests.RequestException, ValueError):
                pass
            time.sleep(min(2**retry, 8))
        raise GatewayError(f"retries_exhausted_{attempts[-1]}")

    def response(self, messages, seed, attempts):
        body = {"model": MODEL, "messages": messages, "tools": strong.TOOLS, "tool_choice": "auto",
                "parallel_tool_calls": False, "stream": False, "temperature": 0.3, "seed": seed,
                "max_tokens": strong.CAP, "enable_thinking": False}
        data = self.generate(body, attempts)
        return data["choices"][0]["message"], data.get("model"), data.get("system_fingerprint")


def source_root(spec):
    return strong.STUDY if spec.module is strong else spec.module.ROOT


def inputs():
    selected = [Path(__file__).resolve()]
    for spec in STUDIES.values():
        selected.append(Path(spec.module.__file__).resolve())
        root = source_root(spec)
        selected.extend(root / name for name in ("protocol.json", "tasks.json", "freeze.json"))
    selected.extend((ROOT / "necessity_v2").glob("*.py"))
    selected += [airgap.ROOT / "gold.json", native.ROOT / "judge-fixtures.json",
                 factorial.ROOT / "judge-fixtures.json"]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(selected))}


def originals():
    strong_frozen = strong.read_json(strong.STUDY / "freeze.json")
    assert strong_frozen["sha256"] == strong.manifest_hashes()
    for spec in STUDIES.values():
        if spec.module is not strong:
            spec.module.verify()


def plan():
    entries = {}
    for name, spec in STUDIES.items():
        protocol = strong.read_json(source_root(spec) / "protocol.json")
        tasks = strong.read_json(source_root(spec) / "tasks.json")
        entries[name] = {"tasks": len(tasks), "arms": protocol["arms"], "seeds": protocol["seeds"],
                         "assigned": len(tasks) * len(protocol["arms"]) * len(protocol["seeds"])}
        assert entries[name]["assigned"] == protocol["episodes"], name
    return entries


def freeze():
    originals()
    manifest = OUT / "freeze.json"
    if manifest.exists():
        raise RuntimeError("Replication already frozen.")
    entries = plan()
    strong.dump(manifest, {"model": MODEL, "assigned": sum(s["assigned"] for s in entries.values()),
                           "studies": entries, "temperature": .3, "thinking": False,
                           "tool_protocol_and_budgets": "original per study",
                           "timing": "retain original event schedule",
                           "primary_scope": "strong baseline, three-way, and AirGap-style adaptation",
                           "diagnostic_scope": "native-tool and text factorials",
                           "hashes": inputs()})


def make_body(spec, messages, seed):
    if spec.mode == "native":
        return {**native.request_body(messages, seed), "model": MODEL}
    return {"model": MODEL, "stream": False, "messages": messages, "temperature": .3,
            "seed": seed, "max_tokens": spec.max_tokens, "enable_thinking": False}


def score_record(spec, case, row, gold):
    if spec.module is strong:
        return strong.score(case, row) | {
            "calls_after_close": sum(e.get("detail") == "workflow_closed" for e in row["events"])}
    if spec.module is airgap:
        return airgap.score(row, case, gold[case["id"]])
    return spec.module.score(row, case)


def legacy_episode(spec, case, arm, seed, gateway):
    turns, attempts = [], []

    def infer(messages, *args):
        role, index = args if len(args) == 2 else ("conversation", args[0])
        body = make_body(spec, messages, seed)
        data = gateway.generate(body, attempts)
        choice = data["choices"][0]
        raw = choice["message"]
        result = raw if spec.mode == "native" else (raw.get("content") or "")
        meta = {"role": role, "index": index, "model_version": data.get("model"),
                "fingerprint": data.get("system_fingerprint"), "usage": data.get("usage") or {},
                "reasoning": raw.get("reasoning_content") or raw.get("reasoning") or "",
                "finish_reason": choice.get("finish_reason")}
        turns.append((result, meta))
        return result, meta

    original = spec.module.episode
    error = None
    try:
        row = original(case, arm, seed, infer)
    except GatewayError as exc:
        error = str(exc)
        # Score the actual returned prefix without fabricating a model reply.
        row = None
        if not (spec.module is airgap and arm == "airgap" and len(turns) < 2):
            prefix = FunctionType(original.__code__, {**original.__globals__, "LIMIT": len(turns)})
            row = prefix(case, arm, seed, lambda messages, *args: turns[args[-1]])
    return row, error, dict(Counter(map(str, attempts))), turns if row is None else []


def run(endpoint, key, workers, selected=None, preflight=False):
    frozen = strong.read_json(OUT / "freeze.json")
    assert frozen["hashes"] == inputs()
    gateway = Gateway(endpoint, key)
    rules = strong.read_json(strong.STUDY / "rules.json")
    system = (strong.STUDY / "system.txt").read_text()
    sources = {name: strong.read_json(source_root(spec) / "tasks.json") for name, spec in STUDIES.items()}
    gold = strong.read_json(airgap.ROOT / "gold.json")
    assert isinstance(gold, dict) and sources["airgap"][0]["id"] in gold
    jobs = []
    for name, spec in STUDIES.items():
        if selected and name not in selected:
            continue
        design = frozen["studies"][name]
        cases = sources[name][:1] if preflight else sources[name]
        seeds = design["seeds"][:1] if preflight else design["seeds"]
        pairs = [(case, seed) for case in cases for seed in seeds]
        random.Random(2026112524).shuffle(pairs)
        arms = design["arms"]
        for i, (case, seed) in enumerate(pairs):
            offset = i % len(arms)
            for arm in arms[offset:] + arms[:offset]:
                jobs.append((name, spec, case, arm, seed))
    folder = OUT / ("preflight" if preflight else "episodes")
    for name in STUDIES:
        (folder / name).mkdir(parents=True, exist_ok=True)

    def work(name, spec, case, arm, seed):
        path = folder / name / f"{case['id']}__{arm}__{seed}.json"
        if path.exists():
            return name, strong.read_json(path)["transport_error"] or "ok"
        if spec.module is strong:
            row = strong.episode(case, arm, seed, gateway, system, rules)
            error = next(iter(row["protocol_errors"][-1:]), None) if row["end"] == "api_error" else None
            statuses, prefix = row["http_statuses"], []
        else:
            row, error, statuses, prefix = legacy_episode(spec, case, arm, seed, gateway)
        score = score_record(spec, case, row, gold) if row is not None else None
        strong.dump(path, {"id": case["id"], "arm": arm, "seed": seed, "row": row, "score": score,
                           "transport_error": error, "http_statuses": statuses, "unscored_prefix": prefix})
        return name, error or "ok"

    counts = Counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        remaining = [pool.submit(work, *job) for job in jobs]
        for i, future in enumerate(as_completed(remaining), 1):
            name, result = future.result()
            counts[(name, result)] += 1
            if i % 12 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)}", dict(counts), flush=True)
    summarize(preflight)


def summarize(preflight=False):
    frozen = strong.read_json(OUT / "freeze.json")
    source = OUT / ("preflight" if preflight else "episodes")
    result = {}
    for name, spec in STUDIES.items():
        rows = [strong.read_json(path) for path in sorted((source / name).glob("*.json"))]
        table = {}
        for arm in frozen["studies"][name]["arms"]:
            assigned = [r for r in rows if r["arm"] == arm]
            totals = Counter()
            for r in assigned:
                if r["score"]:
                    totals.update({k: int(v) for k, v in r["score"].items() if type(v) in (bool, int)
                                   and k not in ("seed", "variant", "state_id")})
            table[arm] = {"recorded": len(assigned), "scored": sum(r["score"] is not None for r in assigned),
                          "gateway_interruptions": sum(bool(r["transport_error"]) for r in assigned), **totals}
        result[name] = {"assigned": frozen["studies"][name]["assigned"], "recorded": len(rows), "arms": table}
    strong.dump(OUT / ("preflight-summary.json" if preflight else "summary.json"), result)
    print({name: (r["recorded"], r["assigned"]) for name, r in result.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "preflight", "run", "summarize"))
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--study", action="append", choices=tuple(STUDIES))
    args = parser.parse_args()
    if args.phase in ("run", "preflight"):
        source = Path(os.environ["STUDY_KEY_PATH"])
        key = source.read_text().strip()
        if os.environ.get("STUDY_EPHEMERAL_KEY") == "1":
            source.unlink()
        run(os.environ["STUDY_GATEWAY_URL"], key, args.workers, args.study, args.phase == "preflight")
    else:
        globals()[args.phase]()
