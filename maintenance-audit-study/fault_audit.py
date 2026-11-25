"""Reconcile a fault trace with the frozen policy and deployed configuration."""
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
import maintenance_audit_study as study


def distinguish(rule, compiled):
    approved_gate = rule["gate"]
    configured = next(((entry, steps) for entry, steps in compiled[4]
                       if entry["id"] == rule["id"]), None)
    if not configured:
        return "missing_rule", {}
    entry, steps = configured
    selected = sorted(steps)
    current_gate = next((action for action in compiled[1] if action.id == approved_gate), None)
    tracked = {"selected_targets": selected, "compiled_gate": approved_gate if current_gate else None}
    if selected != sorted(rule["tool_selector"]):
        return "wrong_selector", tracked
    if not current_gate or not any(action.id == target + "_guarded" and
                                   current_gate.produces in action.requires
                                   for target in selected for action in compiled[1]):
        return "missing_dependency", tracked
    tracked["compiled_predicates"] = current_gate.guards
    tracked["compiled_fields"] = current_gate.fields
    if (rule["when"], True) not in current_gate.guards:
        return "reverse_condition", tracked
    if current_gate.fields != (rule["field"],):
        return "wrong_field", tracked
    return None, tracked


def run():
    assert study.read_json(OUT / "freeze.json") == study.hashes()
    approved = study.read_json(OUT / "rules.json")
    fixtures = study.read_json(OUT / "cases.json")
    result = study.read_json(OUT / "results.json")
    diagnostics = []
    for entry in result["faults"]:
        rule = next(r for r in approved if r["id"] == entry["rule"])
        compiled = study.compile_domain(rule["domain"], entry["arm"], approved, (entry["rule"], entry["fault"]))
        reason, evidence = distinguish(rule, compiled)
        assert reason == entry["fault"]
        failure = entry["violations"][0]
        fixture = fixtures[failure["fixture_index"]]
        diagnostics.append({
            "arm": entry["arm"], "rule": rule["id"], "diagnosis": reason, "configuration_evidence": evidence,
            "example": {"case": failure["fixture_index"], "state": fixture["facts"],
                        "expected": study.expected(fixture), "actual": failure["actual"]},
        })
    study.dump(OUT / "fault-audit.json", diagnostics)
    print(f"Diagnosed {len(diagnostics)} injected changes using frozen rule and compiled configuration.")


if __name__ == "__main__":
    run()
