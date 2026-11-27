"""Add a narrowly scoped refund grant to the frozen state-return experiment."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
DESIGN = json.loads((HERE / "protocol.json").read_text())
source = HERE.parent / "run.py"
spec = importlib.util.spec_from_file_location("gaia_refund_return", source)
study = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = study
spec.loader.exec_module(study)
strong = study.strong


class SelectiveRefundContract(strong.ContractBackend):
    """Keep current-route and per-field checks; bind lifetime to actual bank consent."""

    def __init__(self, authority, registry, policy, goals, consent_epoch):
        super().__init__(authority, registry, policy, goals)
        self.consent_epoch = consent_epoch

    def _session(self, sid):
        # Do not invalidate a bank grant just because route-priority inputs changed.
        return self.current_session(sid)

    def issue(self, sid, node):
        result = super().issue(sid, node)
        if node == "bank":
            self.grants[result["grant"]]["authorization_epoch"] = self.consent_epoch()
        return result

    def read(self, gid, fields, resource):
        grant = self.grants.get(gid)
        if grant and grant["node"] == "bank":
            if grant["authorization_epoch"] != self.consent_epoch():
                raise strong.Denied("stale_authorization_epoch")
        # The original implementation still checks the current session and action,
        # exact field scope, value versions, single use and resource binding.
        return super().read(gid, fields, resource)


class SelectiveStudyWorkflow(study.ReturnWorkflow):
    def __init__(self, case, arm, rules):
        super().__init__(case, "contract" if arm == "selective_contract" else arm, rules)
        if arm == "selective_contract":
            original = self.verifier
            self.verifier = SelectiveRefundContract(
                self.authority, original.registry, original.policy, original.goals,
                lambda: self.consent_epoch,
            )


def verify_contract():
    for case_id, app in study.DESIGN["cases"].items():
        workflow = SelectiveStudyWorkflow(study.fixture(case_id), "selective_contract", study.RULES)
        workflow.status()
        workflow.select_plan(["bank"])
        preparation = workflow.prepare_read("bank")
        _, _, grant, _ = workflow.handles[preparation["handle"]]
        workflow.apply_changes()
        strong.refresh_public_state(workflow.verifier)
        authorized = True
        try:
            workflow.verifier.read(grant, preparation["fields"], workflow.authority.resource)
        except strong.Denied:
            authorized = False
        assert authorized == app["reuse"], (case_id, authorized)
    print("Five direct contract checks passed, independently of the shared delivery wrapper.", flush=True)

    for case_id, expected in study.DESIGN["cases"].items():
        for arm in DESIGN["arms"]:
            workflow = SelectiveStudyWorkflow(study.fixture(case_id), arm, study.RULES)
            workflow.status()
            workflow.select_plan(["bank"])
            preparation = workflow.prepare_read("bank")
            result = workflow.call("read_fields", preparation)
            allowed = "values" in result
            assert allowed == (expected["reuse"] and not (
                case_id == "temporary_priority_return" and arm == "contract"
            ))
            if not allowed:
                workflow.status()
                workflow.select_plan([expected["target"]])
                preparation = workflow.prepare_read(expected["target"])
                result = workflow.call("read_fields", preparation)
            workflow.confirm(expected["target"])
            workflow.execute(expected["target"], result["values"])
            assert workflow.commits == [expected["target"]]
    print("Fifteen scripted end-to-end policy checks passed.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, default=HERE / "results.jsonl")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.verify:
        verify_contract()
        return
    study.ReturnWorkflow = SelectiveStudyWorkflow
    gateway = study.Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])
    jobs = []
    for i, case in enumerate(study.DESIGN["cases"]):
        for j, seed in enumerate(study.DESIGN["seeds"]):
            arms = DESIGN["arms"]
            offset = (i + j) % len(arms)
            jobs.extend((case, arm, seed) for arm in arms[offset:] + arms[:offset])

    def execute(job):
        case, arm, seed = job
        return study.score(case, study.run_business_episode(case, arm, seed, gateway))

    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        seen = {(r["case"], r["arm"], r["seed"]) for r in map(json.loads, output)}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed(pool.submit(execute, job) for job in jobs if job not in seen):
                row = future.result()
                output.write(json.dumps(row) + "\n")
                print({k: v for k, v in row.items() if k not in {"tools", "state_transitions"}}, flush=True)


if __name__ == "__main__":
    main()
