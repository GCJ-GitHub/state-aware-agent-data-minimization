"""Analyze archived model pairs and backend contrasts without calling a model."""
from collections import Counter, defaultdict
from pathlib import Path
import sys

import numpy as np

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
import qwen4_paper_replication as run

FIELDS = {
    "strong": ("correct", "excess_fields", "recovered", "tool_calls", "model_calls", "leak_episode"),
    "three-arm": ("task_success", "hindsight_unused_fields", "expired_evidence_fields", "success_after_block",
                  "tools", "model_calls", "confirmations", "any_leak"),
    "airgap": ("success", "overread_fields", "unauthorized_observed", "tools", "model_calls",
               "data_escalations", "action_confirmations", "any_leak"),
    "native-factorial": ("task_success", "outside_justification_fields", "expired_evidence_fields",
                         "success_after_block", "predicate_queries", "tools", "model_calls", "any_leak"),
    "text-factorial": ("task_success", "outside_justification_fields", "expired_evidence_fields",
                       "success_after_block", "predicate_queries", "tools", "model_calls", "any_leak"),
}
CONTRASTS = {
    "strong": (("contract", "route_table"),),
    "three-arm": (("state_guard", "agent_only"), ("state_guard", "upfront")),
    "airgap": (("state_guard", "airgap"), ("state_guard", "agent_only")),
    "native-factorial": (("planned_enforced", "fixed_enforced"), ("planned_enforced", "planned_soft")),
    "text-factorial": (("planned_enforced", "fixed_enforced"), ("planned_enforced", "planned_soft")),
}


def identity(row):
    return row["id"], row["arm"], row["seed"]


def differences(traces, tasks, keys):
    samples = defaultdict(list)
    for a, b in traces:
        case = tasks[a["id"]]
        group = case.get("pair", case["id"])
        stratum = case.get("family", case.get("kind", "all"))
        samples[stratum, group].append([a[k] - b[k] for k in keys])
    if not samples:
        return {"matched": 0}
    rng = np.random.default_rng(251125)
    strata = defaultdict(list)
    for (stratum, _), values in sorted(samples.items()):
        strata[stratum].append(np.array(values))
    total = np.zeros((5000, len(keys)))
    counts = np.zeros(5000)
    for data in strata.values():
        choice = rng.integers(len(data), size=(5000, len(data)))
        totals = np.array([v.sum(axis=0) for v in data])
        ns = np.array([len(v) for v in data])
        total += totals[choice].sum(axis=1)
        counts += ns[choice].sum(axis=1)
    estimates = np.concatenate(list(samples.values())).mean(axis=0)
    return {
        "matched": sum(map(len, samples.values())), "clusters": len(samples),
        "mean_delta": dict(zip(keys, estimates.tolist())),
        "paired_ci95": dict(zip(keys, np.quantile(total / counts[:, None], [.025, .975], axis=0).T.tolist())),
    }


def analyze():
    manifest = run.strong.read_json(OUT / "freeze.json")
    assert manifest["hashes"] == run.inputs()
    outcomes = {}
    for name, study in run.STUDIES.items():
        root = run.source_root(study)
        task_map = {task["id"]: task for task in run.strong.read_json(root / "tasks.json")}
        measured = [run.strong.read_json(p) for p in sorted((OUT / "episodes" / name).glob("*.json"))]
        baseline = {identity(row): row for row in run.strong.read_json(root / "metrics.json")}
        plan = manifest["studies"][name]
        assigned = {(case, arm, seed) for case in task_map for arm in plan["arms"] for seed in plan["seeds"]}
        assert len({identity(r) for r in measured}) == len(measured)
        assert {identity(r) for r in measured} <= assigned
        scores = {}
        http, end = Counter(), Counter()
        for record in measured:
            http.update(record["http_statuses"])
            if record["score"] is None:
                continue
            case = task_map[record["id"]]
            if study.module is run.airgap:
                gold = run.strong.read_json(root / "gold.json")
            else:
                gold = None
            recomputed = run.score_record(study, case, record["row"], gold)
            assert recomputed == record["score"], identity(record)
            scores[identity(record)] = {"id": record["id"], **recomputed}
            if name == "strong":
                end[record["row"]["end"]] += 1
        ready = len(measured) == len(assigned)
        outcome = {"assigned": len(assigned), "recorded": len(measured), "scored": len(scores),
                   "http": dict(http), "end": dict(end), "complete_matrix": ready}
        if ready:
            outcome["cross_model_by_arm"] = {
                arm: differences([(value, baseline[key]) for key, value in scores.items()
                                  if key[1] == arm and key in baseline], task_map, FIELDS[name])
                for arm in plan["arms"]
            }
            outcome["qwen4_arm_contrasts"] = {
                f"{a}-minus-{b}": differences([(value, scores[(case, b, seed)])
                                              for (case, arm, seed), value in scores.items()
                                              if arm == a and (case, b, seed) in scores],
                                             task_map, FIELDS[name])
                for a, b in CONTRASTS[name]
            }
        outcomes[name] = outcome
    run.strong.dump(OUT / "paired-analysis.json", outcomes)
    for name, row in outcomes.items():
        print(name, row["recorded"], "/", row["assigned"], "scored", row["scored"])


if __name__ == "__main__":
    analyze()
