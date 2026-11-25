"""Compare authored changes, regression oracles and decision logs offline."""
import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
from itertools import product
from pathlib import Path

from necessity_v2.composable_routes import ComposableRouteTable
from necessity_v2.core import Action, Authority, Denied, Policy, Registry, Verifier
from necessity_v2.route_baseline import RouteRow, refresh_public_state
from strong_backend_autonomous import ARMS, ROOT, dump, read_json

OUT = ROOT / "maintenance-audit-study"
BASE = ROOT / "strong-backend-autonomous" / "rules.json"
TAG_FILE = OUT / "recipe-tags.json"
RULE_FILE = OUT / "rules.json"
FAULTS = ("missing_rule", "wrong_selector", "reverse_condition", "wrong_field", "missing_dependency")


def sources(domain):
    spec = read_json(BASE)[domain]
    contracts = []
    for name, goal, deps, fields, guard in spec["contracts"]:
        contracts.append(Action(name, name, goal, tuple(deps), tuple(fields),
                                ((guard, True),) if guard else ()))
    recipes = [
        RouteRow(frozenset({row["goal"]}), root,
                 tuple((n, tuple(fields)) for n, fields in row["steps"].items()),
                 ((row["when"], True),)) for root, row in spec["recipes"].items()
    ]
    return spec, contracts, recipes


def guard_rule(rule, fault):
    """Return one symmetric change to the declaration or dependency wiring."""
    return dict(rule, expected=fault != "reverse_condition",
                effective_field="audit_trap_ref" if fault == "wrong_field" else rule["field"],
                wired=fault != "missing_dependency")


def compile_domain(domain, arm, declarations, mutation=None):
    spec, original, original_rows = sources(domain)
    tags = read_json(TAG_FILE)
    rules = []
    for raw in declarations:
        if raw["domain"] != domain:
            continue
        fault = mutation[1] if mutation and raw["id"] == mutation[0] else None
        if fault == "missing_rule":
            continue
        rule = guard_rule(raw, fault)
        key = "recipe_selector" if arm == "route_table" else "tool_selector"
        selector = rule[key]
        if fault == "wrong_selector":
            selector = "wrong_group" if arm == "route_table" else ["wrong_tool"]
        targets = [a.id for a in original if (tags.get(a.id) == selector if arm == "route_table"
                                             else a.tool in selector)]
        rules.append((rule, targets))
    actions = list(original)
    table = list(original_rows)
    provenance = {}
    for rule, targets in rules:
        fact, gate, value = rule["when"], rule["gate"], rule["effective_field"]
        expected = rule["expected"]
        check = Action(gate, gate, gate + "_done", (), (value,), ((fact, expected),))
        if not rule["wired"]:
            continue
        actions.append(check)
        provenance[gate] = rule["id"]
        for target in targets:
            position = next(i for i, a in enumerate(actions) if a.id == target)
            old = actions[position]
            normal = replace(old, guards=old.guards + ((fact, not expected),))
            guarded = replace(old, id=target + "_guarded",
                              guards=old.guards + ((fact, expected),), requires=old.requires + (check.produces,))
            actions[position] = normal
            actions.append(guarded)
            provenance[guarded.id] = rule["id"]
            if arm == "route_table":
                index = next(i for i, row in enumerate(table) if row.root == target)
                row = table[index]
                ordinary = replace(row, conditions=row.conditions + ((fact, not expected),))
                steps = tuple((guarded.id if step == target else step, fields)
                              for step, fields in row.steps) + ((gate, (value,)),)
                table[index] = ordinary
                table.append(replace(row, root=guarded.id, steps=steps,
                                     conditions=row.conditions + ((fact, expected),)))
    return spec, actions, table, provenance, rules


def fixture(scope, variant, bits, authorized):
    bit1, bit2 = bits
    if scope == "refund":
        states = {"wallet_online": variant == "wallet", "bank_online": variant != "none",
                  "recent_bank_change": bit1}
        goals = ["refund"]
        end = {"wallet": ["wallet"], "bank": ["bank"], "none": []}[variant]
        checks = ["beneficiary_check"] if bit1 and variant == "bank" else []
        lock = {"beneficiary_check": "beneficiary_ref"}
    else:
        states = {"site_open": variant != "closed", "preferred_open": variant == "preferred",
                  "backup_open": variant != "closed", "cross_region": bit1, "restricted_site": bit2}
        goals = ["site_change", "booking"]
        end = ["move", variant + "_slot"] if variant != "closed" else []
        checks = ([] if not end else ["carrier_check"] * bit1 + ["reservation_check"] * bit2)
        lock = {"carrier_check": "carrier_declaration_ref", "reservation_check": "reservation_attestation_ref"}
    fields = {"wallet": "wallet_ref", "bank": "bank_ref", "move": "site_ref",
              "preferred_slot": "preferred_slot_ref", "backup_slot": "backup_slot_ref",
              "identity": "identity_ref", **lock}
    for a in ("bank",):
        if a in end:
            fields[a] = ("bank_ref", "owner_ref")
    required = set(end + checks + (["identity"] if end and scope == "pickup" else []))
    all_locked = set(lock.values())
    if not authorized and checks:
        required.clear()
        end = []
    delivered = sorted({f for a in required for f in ((fields[a],) if isinstance(fields[a], str) else fields[a])})
    return {"domain": scope, "variant": variant, "facts": states, "goals": goals, "authorized": authorized,
            "withheld": sorted(all_locked if not authorized else ()), "branches": sorted(end), "fields": delivered,
            "steps": sorted(required)}


def cases():
    return [
        fixture(scope, variant, bits, authorized)
        for scope, variants, conditions in (
            ("refund", ("wallet", "bank", "none"), ((False, False), (True, False))),
            ("pickup", ("preferred", "backup", "closed"), tuple(product((False, True), repeat=2))),
        )
        for variant, bits, authorized in product(variants, conditions, (False, True))
    ]


def start(case, arm, compiled):
    spec, actions, rows, _, _ = compiled
    raw = {field for a in actions for field in a.fields}
    raw.update({"audit_trap_ref", "beneficiary_ref", "carrier_declaration_ref", "reservation_attestation_ref"})
    values = {key: "SYN-AUDIT-" + key for key in raw}
    authority = Authority("maintenance-fixture", values, case["facts"], case["facts"])
    policy = Policy(frozenset(a.tool for a in actions), frozenset(raw - set(case["withheld"])),
                    tuple((tool, i) for i, tool in enumerate(spec["priority"])), minimize_disclosure=False)
    if arm == "route_table":
        verifier = ComposableRouteTable(authority, actions, policy, case["goals"], rows)
        # Existing workflow-specific identity receipt adapter is unused in this
        # single-session suite; compose the routes and use the core session methods.
    else:
        verifier = Verifier(authority, Registry(actions), policy, case["goals"])
    refresh_public_state(verifier)
    return verifier


def select(verifier):
    plans = verifier.inspect()["plans"]
    if not plans:
        return None, []
    plan = plans[0]["nodes"]
    # Invoke core propose/execute in both arms to avoid the logistics-specific
    # identity receipt convention. Both use identical dependencies and outcomes.
    return Verifier.propose(verifier, plan), plan


def prepare(v, arm, sid, step):
    fields = sorted(f for f in v.registry.actions[step].fields if
                    v.disclosed.get(f) != v.authority.value_version(f))
    grant = v.issue(sid, step)["grant"] if arm == "contract" else None
    return fields, grant


def read(v, arm, sid, node, fields, grant, resource):
    if arm == "contract":
        return v.read(grant, fields, resource)
    return v.read_step(sid, node, fields, resource)


def execute(v, sid, node, values):
    # The inherited table adapter checks identity_verified, whereas these
    # fixtures use the common verified_identity artifact.
    return Verifier.execute(v, sid, node, values)


def evaluate(case, arm, compiled):
    spec = compiled[0]
    v = start(case, arm, compiled)
    sid, names = select(v)
    if sid is None:
        return {"steps": [], "branches": [], "fields": [], "confirmations": 0}
    pending = set(names)
    done, committed, values = [], [], {}
    approvals = set()
    while pending:
        artifacts = v.sessions[sid]["artifacts"]
        name = next(name for name in sorted(pending) if set(v.registry.actions[name].requires) <= artifacts)
        action = v.registry.actions[name]
        fields, ticket = prepare(v, arm, sid, name)
        values.update(read(v, arm, sid, name, fields, ticket, v.authority.resource))
        if action.tool in spec["approval"]:
            approvals.add(name)
        if action.tool in spec["approval"]:
            assert name in approvals
        execute(v, sid, name, {f: values[f] for f in action.fields})
        pending.remove(name)
        done.append(action.tool)
        if action.produces in case["goals"]:
            committed.append(action.tool)
    return {"steps": sorted(done), "branches": sorted(committed), "fields": sorted(values),
            "confirmations": len(approvals)}


def expected(case):
    return {key: case[key] for key in ("steps", "branches", "fields")} | {
        "confirmations": len(case["branches"])}


def audit_trace(arm, scenario, declarations):
    case = fixture("refund", "bank", (scenario not in {"route_changed", "version_changed", "allow_standard"}, False),
                   scenario != "unauthorized")
    compiled = compile_domain("refund", arm, declarations)
    v = start(case, arm, compiled)
    sid, names = select(v)
    authority = v.authority
    step = ("bank_guarded" if case["facts"]["recent_bank_change"] else "bank")
    action = v.registry.actions[step]
    gate = "beneficiary_check"
    field = "beneficiary_ref"
    grant, delivered, native_error = None, {}, None
    requested = sorted(action.fields)
    prepared_versions = {f: authority.fact_version(f) for f in authority.public}
    if sid and scenario != "missing_prerequisite":
        if gate in names:
            inputs, token = prepare(v, arm, sid, gate)
            values = read(v, arm, sid, gate, inputs, token, authority.resource)
            execute(v, sid, gate, values)
        requested, grant = prepare(v, arm, sid, step)
    if scenario in {"route_changed", "version_changed"}:
        authority.update_fact("wallet_online", scenario == "route_changed")
    if scenario == "wrong_fields":
        requested += ["audit_trap_ref"]
    resource = "foreign-fixture" if scenario == "wrong_scope" else authority.resource
    verified = bool(sid and v.sessions[sid]["artifacts"])
    snapshots = {f: {"value": authority._facts[f][0], "version": authority.fact_version(f)}
                 for f in sorted(authority.public)}
    try:
        if sid is None:
            Verifier.propose(v, [step, gate])
        elif arm == "contract" and scenario == "missing_prerequisite":
            prepare(v, arm, sid, step)
        else:
            delivered = read(v, arm, sid, step, requested, grant, resource)
    except Denied as error:
        native_error = str(error)
    current = {plan["nodes"][i] for plan in fresh_plans(v) for i in range(len(plan["nodes"]))}
    if resource != authority.resource:
        verdict = "wrong_scope"
    elif sid is None and field not in v.policy.allowed_fields and action.requires:
        verdict = "unauthorized"
    elif step not in current:
        verdict = "route_changed"
    elif action.requires and not verified:
        verdict = "missing_prerequisite"
    elif set(requested) != set(action.fields):
        verdict = "wrong_fields"
    elif native_error:
        verdict = "version_changed"
    elif action.requires:
        verdict = "allow_after_check"
    else:
        verdict = "allow_standard"
    return {
        "case": scenario, "arm": arm, "allowed": native_error is None,
        "native": {"message": native_error,
                   "events": [e for e in v.events if e["kind"] == "read" and e.get("node") == step]},
        "structured": {
            "decision": "deny" if native_error else "allow", "reason": verdict,
            "requested_step": step, "requested_fields": requested, "step_fields": sorted(action.fields),
            "rule_id": compiled[3].get(step),
            "prerequisites": list(action.requires), "verification_present": verified,
            "scope_ok": resource == authority.resource,
            "authorization_for_verification_field": field in v.policy.allowed_fields,
            "status": snapshots, "prepared_state_versions": prepared_versions,
            "grant_version_check": arm == "contract", "delivered_fields": sorted(delivered),
        },
    }


def fresh_plans(v):
    refresh_public_state(v)
    return v.inspect()["plans"]


def recover_reason(record):
    """Use decision logs alone to classify the incident, without fixture labels."""
    if not record["scope_ok"]:
        return "wrong_scope"
    if not record["authorization_for_verification_field"] and record["prerequisites"]:
        return "unauthorized"
    if record["status"]["wallet_online"]["value"] and record["requested_step"].startswith("bank"):
        return "route_changed"
    if record["prerequisites"] and not record["verification_present"]:
        return "missing_prerequisite"
    if set(record["requested_fields"]) != set(record["step_fields"]):
        return "wrong_fields"
    if record["decision"] == "deny" and record["grant_version_check"] and any(
        record["prepared_state_versions"][fact] != item["version"] for fact, item in record["status"].items()
    ):
        return "version_changed"
    return "allow_after_check" if record["prerequisites"] else "allow_standard"


def hashes():
    files = [Path(__file__).resolve(), BASE, TAG_FILE, RULE_FILE, OUT / "cases.json"]
    files += list((ROOT / "necessity_v2").glob("*.py"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def config_stats(arm, rules):
    stats = Counter(authored_rule_records=len(rules))
    for domain in ("refund", "pickup"):
        _, before, old_recipes = sources(domain)
        _, after, rows, _, selected = compile_domain(domain, arm, rules)
        orig, new = {a.id: a for a in before}, {a.id: a for a in after}
        immediate = {row.root: row for row in old_recipes}
        later = {row.root: row for row in rows}
        stats["authored_selector_entries"] += sum(
            1 if arm == "route_table" else len(rule["tool_selector"]) for rule, _ in selected)
        stats["original_operations_changed"] += sum(new[key] != value for key, value in orig.items())
        stats["generated_operations_added"] += len(new.keys() - orig.keys())
        stats["existing_recipes_changed"] += sum(later[key] != value for key, value in immediate.items())
        stats["generated_recipes_added"] += len(later.keys() - immediate.keys())
    return dict(stats)


def run():
    assert read_json(OUT / "freeze.json") == hashes()
    declarations, fixtures = read_json(RULE_FILE), read_json(OUT / "cases.json")
    output, regression, mutants, audit = {}, [], [], []
    for arm in ARMS:
        clean = {d: compile_domain(d, arm, declarations) for d in ("refund", "pickup")}
        results = [evaluate(f, arm, clean[f["domain"]]) for f in fixtures]
        assert results == [expected(f) for f in fixtures]
        for f, result in zip(fixtures, results):
            active = any(f["facts"].get(rule["when"], False) for rule in declarations)
            if not active:
                before = evaluate(f, arm, compile_domain(f["domain"], arm, []))
                assert before == result
                regression.append({"arm": arm, "fixture": f, "before": before, "after": result})
        for rule in declarations:
            domain = rule["domain"]
            for fault in FAULTS:
                mutated = compile_domain(domain, arm, declarations, (rule["id"], fault))
                details = []
                for index, f in enumerate(fixtures):
                    if f["domain"] != domain:
                        continue
                    got = evaluate(f, arm, mutated)
                    want = expected(f)
                    if got != want:
                        details.append({"fixture_index": index,
                                        "excess": sorted(set(got["fields"]) - set(want["fields"])),
                                        "wrong_business": got["branches"] != want["branches"],
                                        "missing_verification": sorted(set(want["steps"]) - set(got["steps"])),
                                        "actual": got})
                mutants.append({"arm": arm, "rule": rule["id"], "fault": fault, "violations": details})
        for scenario in ("allow_standard", "allow_after_check", "unauthorized", "missing_prerequisite",
                         "wrong_fields", "wrong_scope", "route_changed", "version_changed"):
            record = audit_trace(arm, scenario, declarations)
            expected_reason = ("allow_standard" if scenario == "version_changed" and arm == "route_table"
                               else scenario)
            assert recover_reason(record["structured"]) == expected_reason, record
            assert record["allowed"] == expected_reason.startswith("allow_"), record
            audit.append(record)
        subset = [m for m in mutants if m["arm"] == arm]
        by_arm = [a for a in audit if a["arm"] == arm]
        output[arm] = {
            "changes": config_stats(arm, declarations), "clean_correct": len(results),
            "legacy_same": sum(r["arm"] == arm for r in regression),
            "mutants_detected": sum(bool(m["violations"]) for m in subset),
            "mutants_with_excess": sum(any(d["excess"] for d in m["violations"]) for m in subset),
            "mutants_with_wrong_business": sum(any(d["wrong_business"] for d in m["violations"]) for m in subset),
            "mutants_with_missing_verification": sum(any(d["missing_verification"] for d in m["violations"]) for m in subset),
            "structured_reconstructable": len(by_arm),
            "native_read_success_event": sum(bool(a["native"]["events"]) for a in by_arm),
            "native_denial_message": sum(bool(a["native"]["message"]) for a in by_arm),
            "native_rule_id": sum(any("rule_id" in e for e in a["native"]["events"]) for a in by_arm),
        }
    dump(OUT / "results.json", {"summary": output, "regression": regression, "faults": mutants, "audit": audit})
    print(output, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["freeze", "run"])
    if p.parse_args().phase == "freeze":
        if (OUT / "freeze.json").exists():
            p.error("Study already frozen.")
        dump(OUT / "cases.json", cases())
        dump(OUT / "freeze.json", hashes())
    else:
        run()
