"""Controlled implementation-change and decision-audit study for refund rules."""
import copy
from dataclasses import dataclass
import hashlib
import importlib.util
from itertools import product
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from necessity_v2.composable_routes import ComposableRouteTable
from necessity_v2.core import Action, Authority, Denied, Policy, Registry
from necessity_v2.route_baseline import RouteRow, refresh_public_state

source = HERE.parent / "refund-state-return-study" / "selective-contract" / "run.py"
module = importlib.util.spec_from_file_location("selective_refund_maintenance", source)
selective = importlib.util.module_from_spec(module)
sys.modules[module.name] = selective
module.loader.exec_module(selective)

RULES = json.loads((HERE / "rules.json").read_text())
ARMS = ("route_table", "selective_contract")
EXTRA = ("screening_ref", "beneficiary_ref", "review_ref")
FAMILIES = {
    "no_route": (False, False),
    "bank_only": (False, True),
    "wallet_only": (True, False),
    "wallet_preferred": (True, True),
}
FAULTS = ("omit_beneficiary", "wrong_review_field", "miss_wallet_target")
FLAGS = RULES["flags"]


def declarations(fault=None):
    rows = copy.deepcopy(RULES["additions"])
    if fault == "omit_beneficiary":
        rows = [row for row in rows if row["id"] != "R2"]
    if fault == "wrong_review_field":
        rows[2]["field"] = "decoy_ref"
    if fault == "miss_wallet_target":
        rows[0]["paths"].remove("wallet")
    return rows


def compile_rules(added):
    """One authored overlay vocabulary, deployed as recipes or contract actions."""
    rules = declarations() if added is True else declarations(added) if added else []
    actions, recipes = {}, []
    for route, fields in RULES["base"].items():
        relevant = [flag for flag in FLAGS if any(route in r["paths"] and flag in r["when_any"] for r in rules)]
        for bits in product((False, True), repeat=len(relevant)):
            flags = dict(zip(relevant, bits))
            active = [r for r in rules if route in r["paths"] and any(flags[k] for k in r["when_any"])]
            suffix = "".join(str(int(bit)) for bit in bits)
            marker = route + (f"_{suffix}" if suffix else "")
            guards = ((route + "_online", True), *flags.items())
            completed_rules, steps = {}, []
            for rule in active:
                name = f"{marker}_{rule['id']}"
                depends = tuple(completed_rules[r] for r in rule["after"] if r in completed_rules)
                action = Action(name, rule["id"], name + "_ok", depends, (rule["field"],), guards)
                actions[name] = action
                completed_rules[rule["id"]] = action.produces
                steps.append((name, action.fields))
            commit = Action(marker, route, "refund", tuple(completed_rules.values()), tuple(fields), guards)
            actions[marker] = commit
            recipes.append(RouteRow(frozenset({"refund"}), marker, tuple(steps + [(marker, commit.fields)]), guards))
    return list(actions.values()), recipes


@dataclass(frozen=True)
class Prepared:
    sid: str
    node: str
    fields: tuple
    versions: tuple
    epoch: int
    grant: str | None


class Trial:
    def __init__(self, arm, compiled, family, flags, withheld=()):
        actions, recipes = compiled
        self.arm = arm
        facts = dict(zip(("wallet_online", "bank_online"), FAMILIES[family]))
        facts.update(zip(FLAGS, flags))
        fields = set(EXTRA) | {"wallet_ref", "bank_ref", "owner_ref", "decoy_ref"}
        self.authority = Authority("sim-refund", {f: "SIM-" + f for f in fields}, facts, facts)
        self.consent = 1
        policy = Policy(frozenset(a.tool for a in actions), frozenset(fields - set(withheld)),
                        tuple((route, n) for n, route in enumerate(RULES["priority"])), minimize_disclosure=False)
        if arm == "route_table":
            self.verifier = ComposableRouteTable(self.authority, actions, policy, ["refund"], recipes)
        else:
            self.verifier = selective.SelectiveRefundContract(
                self.authority, Registry(actions), policy, ["refund"], lambda: self.consent
            )
        self.refresh()

    def refresh(self):
        refresh_public_state(self.verifier)

    def start(self):
        plans = self.verifier.inspect()["plans"]
        return self.verifier.propose(plans[0]["nodes"]) if plans else None

    def prepare(self, sid, node):
        v = self.verifier
        self.refresh()
        session = v.sessions[sid]
        action = v._enabled(session, node)
        fields = tuple(sorted(action.fields))
        grant = v.issue(sid, node)["grant"] if self.arm != "route_table" else None
        return Prepared(sid, node, fields, tuple(self.authority.value_version(f) for f in fields), self.consent, grant)

    def deliver(self, p, requested=None):
        v = self.verifier
        self.refresh()
        current = v.frontier()["accepted_plans"]
        action = v.registry.actions[p.node]
        session = v.sessions[p.sid]
        requested = p.fields if requested is None else requested
        bank = any(v.registry.actions[n].tool == "bank" for n in session["plan"].roots)
        log = {
            "operation": action.tool,
            "active_plan": session["plan"].id in {plan.id for plan in current},
            "current_plan_ids": sorted(plan.id for plan in current),
            "requested_plan_id": session["plan"].id,
            "state": {name: v.fact(name) for name in sorted(self.authority.public)},
            "consent_at_issue": p.epoch,
            "consent_now": self.consent,
            "checks_bank_authorization": bank,
            "changed_fields": [f for f, old in zip(p.fields, p.versions) if self.authority.value_version(f) != old],
            "required_prerequisites": sorted(action.requires),
            "completed_prerequisites": sorted(session["artifacts"]),
            "missing_prerequisites": sorted(set(action.requires) - session["artifacts"]),
            "field_versions_at_issue": dict(zip(p.fields, p.versions)),
            "field_versions_now": {f: self.authority.value_version(f) for f in p.fields},
            "configured_rules": sorted(
                v.registry.actions[n].tool for n in session["plan"].nodes if v.registry.actions[n].tool.startswith("R")
            ),
            "requested_fields": list(requested),
            "expected_fields": list(p.fields),
        }
        try:
            if not log["active_plan"]:
                raise Denied("current_route")
            if bank and p.epoch != self.consent:
                raise Denied("revoked_authorization")
            if log["changed_fields"]:
                raise Denied("field_version")
            v._enabled(session, p.node)
            if tuple(sorted(requested)) != p.fields:
                raise Denied("field_scope")
            values = v.read(p.grant, requested, self.authority.resource) if p.grant else v.read_step(
                p.sid, p.node, requested, self.authority.resource
            )
            decision = "allow"
        except Denied as err:
            values, decision = {}, str(err)
        return values, log | {"decision": decision, "delivered_fields": sorted(values)}


def oracle(family, flags, withheld, added):
    """Reference outcomes independently authored from the frozen business requirements."""
    enhanced, recent, large = flags if added else (False, False, False)
    for route, enabled in zip(("wallet", "bank"), FAMILIES[family]):
        if not enabled:
            continue
        checks = []
        fields = ["wallet_ref"] if route == "wallet" else ["bank_ref", "owner_ref"]
        if enhanced or large:
            checks.append("R1")
            fields.append("screening_ref")
        if route == "bank" and recent:
            checks.append("R2")
            fields.append("beneficiary_ref")
        if large:
            checks.append("R3")
            fields.append("review_ref")
        if not set(fields) & set(withheld):
            return route, checks, sorted(fields), 1
    return None, [], [], 0


def evaluate(arm, compiled, family, flags, withheld):
    t = Trial(arm, compiled, family, flags, withheld)
    v = t.verifier
    sid = t.start()
    if sid is None:
        return None, [], [], 0
    session = v.sessions[sid]
    order, fields, approvals = [], [], 0
    while "refund" not in v.committed_goals:
        pending = session["plan"].nodes - session["done"]
        nodes = sorted(n for n in pending if set(v.registry.actions[n].requires) <= session["artifacts"])
        node = nodes[0]
        action = v.registry.actions[node]
        values, log = t.deliver(t.prepare(sid, node))
        assert log["decision"] == "allow"
        fields.extend(values)
        if action.produces == "refund":
            approvals += 1  # scripted user confirmation, same for both implementations
        v.execute(sid, node, values)
        order.append(action.tool)
    return order[-1], order[:-1], sorted(fields), approvals


def reconstruct(log):
    if not log["active_plan"]:
        return "current_route"
    if log["checks_bank_authorization"] and log["consent_now"] != log["consent_at_issue"]:
        return "revoked_authorization"
    if log["changed_fields"]:
        return "field_version"
    if log["missing_prerequisites"]:
        return "Action dependencies are not completed."
    if log["requested_fields"] != log["expected_fields"]:
        return "field_scope"
    return "allow"


def audit(arm, compiled):
    result = {}
    for reason in ("plain_allow", "composed_allow", "current_route", "revoked_authorization", "field_version", "field_scope", "missing_prerequisite"):
        composed = reason in {"composed_allow", "missing_prerequisite"}
        t = Trial(arm, compiled, "bank_only", (composed, composed, composed))
        v = t.verifier
        sid = t.start()
        if composed:
            session = v.sessions[sid]
            while len(session["done"]) < 3:
                next_check = next(n for n in sorted(session["plan"].nodes - session["done"])
                                  if v.registry.actions[n].tool.startswith("R")
                                  and set(v.registry.actions[n].requires) <= session["artifacts"])
                values, _ = t.deliver(t.prepare(sid, next_check))
                v.execute(sid, next_check, values)
        node = next(iter(v.sessions[sid]["plan"].roots))
        pending = t.prepare(sid, node)
        if reason == "current_route":
            t.authority.update_fact("wallet_online", True)
        if reason == "revoked_authorization":
            t.authority.update_fact("bank_online", False)
            t.consent += 1
            t.authority.update_fact("bank_online", True)
        if reason == "field_version":
            t.authority.update_value("bank_ref", "SIM-ROTATED")
        if reason == "missing_prerequisite":
            v.sessions[sid]["artifacts"].remove(v.registry.actions[node].requires[0])
        requested = pending.fields + ("decoy_ref",) if reason == "field_scope" else None
        _, log = t.deliver(pending, requested)
        expected = {
            "plain_allow": "allow", "composed_allow": "allow",
            "missing_prerequisite": "Action dependencies are not completed.",
        }.get(reason, reason)
        assert reconstruct(log) == log["decision"] == expected
        assert bool(log["delivered_fields"]) == (expected == "allow")
        result[reason] = log | {"independently_reconstructed": reconstruct(log)}
    return result


def config_differences(approved, deployed):
    intended = {rule["id"]: rule for rule in approved}
    actual = {rule["id"]: rule for rule in deployed}
    differences = []
    for rule_id, rule in intended.items():
        if rule_id not in actual:
            differences.append({"rule": rule_id, "key": "declaration", "approved": rule, "deployed": None})
            continue
        for key, value in rule.items():
            if actual[rule_id].get(key) != value:
                differences.append({
                    "rule": rule_id, "key": key, "approved": value, "deployed": actual[rule_id].get(key)
                })
    return differences


def run():
    old, new = compile_rules(False), compile_rules(True)
    fixtures = [
        (family, flags, tuple(f for f, bit in zip(EXTRA, mask) if bit))
        for family, flags, mask in product(FAMILIES, product((False, True), repeat=3), product((False, True), repeat=3))
    ]
    result = {
        "frozen_rules_sha256": hashlib.sha256((HERE / "rules.json").read_bytes()).hexdigest(),
        "case_count": len(fixtures),
        "arms": {},
        "legacy_impact": {
            "targeted": ["bank_only", "wallet_only", "wallet_preferred"],
            "common_stop_smoke": ["no_route"],
        },
    }
    for arm in ARMS:
        records = []
        for family, bits, withheld in fixtures:
            expected = oracle(family, bits, withheld, True)
            observed = evaluate(arm, new, family, bits, withheld)
            records.append({
                "family": family, "flags": bits, "withheld": withheld, "expected": expected, "observed": observed,
                "false_allow": bool(set(observed[2]) - set(expected[2])),
                "legacy_ok": evaluate(arm, old, family, bits, withheld) == observed if not any(bits) else None,
            })
        faults = {}
        for fault in FAULTS:
            mutated = compile_rules(fault)
            witness = None
            variants = 0
            for family, bits, withheld in fixtures:
                actual = evaluate(arm, mutated, family, bits, withheld)
                expected = oracle(family, bits, withheld, True)
                if actual != expected:
                    variants += 1
                    if witness is None:
                        witness = {"family": family, "flags": bits, "withheld": withheld,
                                   "approved": expected, "deployed": actual}
            assert variants
            differences = config_differences(declarations(), declarations(fault))
            assert len(differences) == 1
            faults[fault] = {"divergent_cases": variants, "configuration_diff": differences[0], "witness": witness}
        result["arms"][arm] = {
            "correct": sum(r["expected"] == r["observed"] for r in records),
            "false_allow_cases": sum(r["false_allow"] for r in records),
            "refund_commits": sum(r["observed"][0] is not None for r in records),
            "safe_stops": sum(r["observed"][0] is None for r in records),
            "legacy_pass": sum(r["legacy_ok"] is True for r in records),
            "legacy_total": sum(r["legacy_ok"] is not None for r in records),
            "authored_additions": len(RULES["additions"]),
            "existing_authored_records_modified": 0,
            "authored_target_entries": sum(len(r["paths"]) for r in RULES["additions"]),
            "authored_dependency_entries": sum(len(r["after"]) for r in RULES["additions"]),
            "generated_action_entries_before_after": [len(old[0]), len(new[0])],
            "generated_route_entries_before_after": [len(old[1]), len(new[1])] if arm == "route_table" else [0, 0],
            "audit": audit(arm, new),
            "faults": faults,
            "cases": records,
        }
        assert result["arms"][arm]["correct"] == len(fixtures)
        assert result["arms"][arm]["false_allow_cases"] == 0
        assert result["arms"][arm]["legacy_pass"] == result["arms"][arm]["legacy_total"]
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    for arm, values in result["arms"].items():
        print(arm, {k:v for k,v in values.items() if k not in {"audit","cases","faults"}})


if __name__ == "__main__":
    run()
