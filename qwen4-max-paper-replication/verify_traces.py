"""Replay stored model outputs against the frozen adapters without API requests."""
from collections import Counter
import importlib.util
from pathlib import Path
import sys
from types import FunctionType

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
import qwen4_paper_replication as replication


def import_strong_audit():
    path = replication.strong.STUDY / "audit.py"
    location = importlib.util.spec_from_file_location("strong_replication_audit", path)
    module = importlib.util.module_from_spec(location)
    location.loader.exec_module(module)
    return module


def outputs_for(study, row):
    if study.mode == "native":
        return row["native_messages"]
    if study.module is replication.airgap:
        return [*row["minimizer_outputs"], *row["outputs"]]
    return row["outputs"]


def replay_legacy(spec, case, record):
    row = record["row"]
    outputs = outputs_for(spec, row)
    meta = row["requests"]
    assert len(outputs) == len(meta)

    def infer(messages, *args):
        index = args[-1]
        assert meta[index]["index"] == index
        return outputs[index], meta[index]

    handler = spec.module.episode
    if record["transport_error"]:
        handler = FunctionType(handler.__code__, {**handler.__globals__, "LIMIT": len(meta)})
    assert handler(case, record["arm"], record["seed"], infer) == row, case["id"]


def main():
    strong = replication.strong
    manifest = strong.read_json(OUT / "freeze.json")
    assert manifest["hashes"] == replication.inputs()
    strong_audit = import_strong_audit()
    strong_rules = strong.read_json(strong.STUDY / "rules.json")
    stats = {}
    for name, spec in replication.STUDIES.items():
        root = replication.source_root(spec)
        tasks = {c["id"]: c for c in strong.read_json(root / "tasks.json")}
        count = Counter()
        for path in sorted((OUT / "episodes" / name).glob("*.json")):
            record = strong.read_json(path)
            case = tasks[record["id"]]
            if record["row"] is None:
                assert record["transport_error"] and spec.module is replication.airgap
                count["unscored_interrupted_prefix"] += 1
                continue
            if spec.module is strong:
                strong_audit.replay(case, record["row"], strong_rules)
                strong_audit.independent_counts(case, record["row"])
            else:
                replay_legacy(spec, case, record)
            count["replayed"] += 1
        stats[name] = dict(count)
    strong.dump(OUT / "trace-audit.json", {"frozen_inputs_verified": True, "counts": stats})
    print(stats)


if __name__ == "__main__":
    main()
