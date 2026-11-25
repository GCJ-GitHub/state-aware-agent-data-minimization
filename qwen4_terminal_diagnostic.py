"""Test one explicit workflow-closed tool response on matched archived runs."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from types import FunctionType

import qwen4_paper_replication as replica

strong = replica.strong
OUT = strong.ROOT / "qwen4-terminal-diagnostic"


class TerminalFeedback(strong.Workflow):
    def call(self, name, args):
        if self.terminal:
            self.events.append({"event": "denial", "tool": name, "turn": self.turn,
                                "code": "workflow_closed", "detail": "workflow_closed"})
            return {"status": "workflow_closed", "complete": not self.stop_called,
                    "stopped": self.stop_called,
                    "feedback": "The workflow is finished. Return a brief final reply now without using tools."}
        return super().call(name, args)


episode = FunctionType(strong.episode.__code__, {**strong.episode.__globals__, "Workflow": TerminalFeedback})


def targets(tasks):
    old = replica.OUT / "episodes" / "strong"
    selected = []
    for family in strong.FAMILIES:
        for variant in ("event", "control"):
            for case in tasks:
                # Separate these cases from the six compatibility-pilot tasks.
                if case["family"] != family or case["variant"] != variant:
                    continue
                if case["id"].endswith(("-01-event", "-02-control")):
                    continue
                if variant == "control" and not case["fact_updates"]:
                    continue
                for seed in strong.SEEDS:
                    if all((old / f"{case['id']}__{arm}__{seed}.json").is_file() for arm in strong.ARMS):
                        selected.append({"id": case["id"], "seed": seed})
                        break
                else:
                    continue
                break
            else:
                raise RuntimeError("Missing prior records for an eligible matched case.")
    return selected


def run():
    old = replica.OUT / "episodes" / "strong"
    tasks = strong.read_json(strong.STUDY / "tasks.json")
    by_id = {c["id"]: c for c in tasks}
    frozen = OUT / "protocol.json"
    if not frozen.exists():
        strong.dump(frozen, {"selected": targets(tasks), "model": replica.MODEL,
                             "only_change": "Reply to a native call after business closure with explicit terminal feedback.",
                             "selection": "First case/seed per family and fixed variant with both baseline arms recorded; "
                                          "excludes prior compatibility pilot; selection does not query outcomes."})
    design = strong.read_json(frozen)
    key_file = Path(os.environ["STUDY_KEY_PATH"])
    key = key_file.read_text().strip()
    key_file.unlink()
    gateway = replica.Gateway(os.environ["STUDY_GATEWAY_URL"], key)
    rules = strong.read_json(strong.STUDY / "rules.json")
    system = (strong.STUDY / "system.txt").read_text()
    jobs = [(by_id[task["id"]], arm, task["seed"]) for task in design["selected"] for arm in strong.ARMS]

    def compare(job):
        case, arm, seed = job
        trace_id = f"{case['id']}__{arm}__{seed}.json"
        path = OUT / trace_id
        if path.exists():
            updated = strong.read_json(path)
        else:
            updated = episode(case, arm, seed, gateway, system, rules)
            strong.dump(path, updated)
        baseline = strong.read_json(old / trace_id)["row"]
        return [replica.score_record(replica.STUDIES["strong"], case, row, None)
                for row in (baseline, updated)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        comparisons = list(pool.map(compare, jobs))
    totals = {}
    for index, condition in enumerate(("original", "explicit_closed_reply")):
        result = Counter()
        for comparison in comparisons:
            result.update(comparison[index])
        totals[condition] = dict(result)
    strong.dump(OUT / "summary.json", {"episodes": len(comparisons), "totals": totals,
                                      "paired_scores": comparisons})
    print({c: {k: t[k] for k in ("correct", "final_reply", "excess_fields", "tool_calls", "calls_after_close")}
           for c, t in totals.items()}, flush=True)


if __name__ == "__main__":
    run()
