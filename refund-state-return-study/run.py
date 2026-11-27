"""Paired refund stress test using the existing autonomous backends."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import strong_backend_autonomous as strong
from qwen4_paper_replication import Gateway

DESIGN = strong.read_json(HERE / "protocol.json")
RULES = strong.read_json(strong.STUDY / "rules.json")
SYSTEM = (strong.STUDY / "system.txt").read_text()
BASE_WORKFLOW = strong.Workflow


@dataclass(frozen=True)
class ReadOrigin:
    consent_epoch: int
    fields: tuple
    field_versions: tuple


def fixture(case_id):
    return {
        "id": case_id,
        "pair": case_id,
        "domain": "refund",
        "checkpoint": "first_valid_delivery",
        "request": DESIGN["request"],
        "initial": {"wallet_online": False, "bank_online": True},
        "allowed": ["wallet_ref", "bank_ref", "owner_ref"],
        "values": {
            "wallet_ref": "SIM-WALLET-309",
            "bank_ref": "SIM-BANK-702",
            "owner_ref": "SIM-OWNER-506",
            "case_note": "initial synthetic annotation",
        },
    }


class ReturnWorkflow(BASE_WORKFLOW):
    def __init__(self, case, arm, rules):
        super().__init__(case, arm, rules)
        self.origins = {}
        self.consent_epoch = 1
        self.challenge_done = False
        self.applied_changes = []

    def tick(self, turn):
        # The first valid delivery attempt is the shared physical checkpoint.
        self.turn = turn

    def prepare_read(self, step):
        response = super().prepare_read(step)
        if "handle" in response:
            fields = tuple(sorted(response["fields"]))
            self.origins[response["handle"]] = ReadOrigin(
                self.consent_epoch, fields, tuple(self.authority.value_version(f) for f in fields)
            )
        return response

    def apply_changes(self):
        for event in DESIGN["cases"][self.case["id"]]["events"]:
            if event in {"wallet_online", "wallet_offline"}:
                self.authority.update_fact("wallet_online", event == "wallet_online")
            elif event in {"consent_revoked", "consent_reissued"}:
                self.consent_epoch += 1
                self.authority.update_fact("bank_online", event == "consent_reissued")
            elif event == "case_note_changed":
                self.authority.update_value("case_note", "revised internal annotation")
            elif event == "bank_reference_rotated":
                self.authority.update_value("bank_ref", "SIM-BANK-921")
            else:
                raise ValueError(f"Unknown frozen event: {event}")
            self.applied_changes.append({
                "kind": event,
                "bank_authorized": self.authority._facts["bank_online"][0],
                "wallet_available": self.authority._facts["wallet_online"][0],
                "consent_epoch": self.consent_epoch,
            })

    def read_fields(self, handle, fields):
        origin = self.origins.get(handle)
        saved = self.handles.get(handle)
        if origin is None or saved is None or tuple(sorted(fields)) != origin.fields:
            raise strong.Denied("invalid_read_handle_or_fields")
        sid, step, _, _ = saved
        if sid != self.session:
            raise strong.Denied("unknown_handle")
        challenge = not self.challenge_done and step == "bank"
        if challenge:
            self.challenge_done = True
            self.apply_changes()
        trace = None
        if challenge:
            trace = {
                "event": "first_old_delivery",
                "turn": self.turn,
                "allowed": False,
                "active_wallet": self.authority._facts["wallet_online"][0],
                "authorization_changed": origin.consent_epoch != self.consent_epoch,
                "transitions": self.applied_changes,
            }
            self.events.append(trace)
        try:
            if step == "bank" and origin.consent_epoch != self.consent_epoch:
                raise strong.Denied("stale_authorization_epoch")
            current_versions = tuple(self.authority.value_version(f) for f in origin.fields)
            if origin.field_versions != current_versions:
                raise strong.Denied("stale_value_version")
            response = super().read_fields(handle, fields)
        except strong.Denied as error:
            if challenge:
                trace["reason"] = str(error)
            # A denied old pending request is consumed in both groups.
            self.handles.pop(handle, None)
            raise
        if challenge:
            trace["allowed"] = True
            trace["fields_delivered"] = sorted(response["values"])
        return response


def run_business_episode(case_id, arm, seed, gateway):
    """Keep the shared native interface and stop at the actual business commit."""
    case = fixture(case_id)
    workflow = ReturnWorkflow(case, arm, RULES)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": case["request"]},
    ]
    calls, attempts = [], []
    recovery = 0
    end = "turn_limit"
    for turn in range(strong.TURNS):
        workflow.tick(turn)
        try:
            raw, _, _ = gateway.response(messages, seed, attempts)
        except RuntimeError:
            end = "api_error"
            break
        wire = {"role": "assistant", "content": raw.get("content") or None}
        invalid_calls = raw.get("tool_calls") or []
        if invalid_calls:
            wire["tool_calls"] = invalid_calls
        messages.append(wire)
        decoded, error = strong.parse_call(raw)
        if decoded:
            name, args, call_id = decoded
            response = workflow.call(name, args)
            calls.append({"turn": turn, "name": name})
            if workflow.terminal:
                end = "committed" if workflow.commits else "stopped"
                break
            messages.append({
                "role": "tool", "tool_call_id": call_id, "content": json.dumps(response)
            })
            continue
        if recovery == strong.RECOVERIES or any(not call.get("id") for call in invalid_calls):
            end = "protocol_stop"
            break
        recovery += 1
        for call in invalid_calls:
            messages.append({
                "role": "tool", "tool_call_id": call["id"],
                "content": json.dumps({"error": error, "executed": False}),
            })
        messages.append({
            "role": "user",
            "content": "Continue the original workflow with one valid native tool call and complete arguments.",
        })
    return {
        "arm": arm, "seed": seed, "events": workflow.events, "commits": workflow.commits,
        "end": end, "calls": calls, "http_statuses": dict(Counter(map(str, attempts))),
    }



def score(case_id, row):
    rules = DESIGN["cases"][case_id]
    old = next((event for event in row["events"] if event["event"] == "first_old_delivery"), None)
    tool_calls = row["calls"]
    first_index = next((i for i, call in enumerate(tool_calls) if old and call["turn"] == old["turn"]), None)
    post = tool_calls[first_index + 1:] if first_index is not None else []
    committed = row["commits"] == [rules["target"]]
    return {
        "case": case_id,
        "arm": row["arm"],
        "seed": row["seed"],
        "end": row["end"],
        "transport_error": row["end"] == "api_error",
        "old_expected_allowed": rules["reuse"],
        "old_observed_allowed": old["allowed"] if old else None,
        "old_reason": old.get("reason") if old else None,
        "old_delivered_fields": old.get("fields_delivered", []) if old else [],
        "false_allow": bool(old and old["allowed"] and not rules["reuse"]),
        "false_reject": bool(old and not old["allowed"] and rules["reuse"]),
        "correct_commit": committed,
        "state_transitions": old["transitions"] if old else [],
        "tools_until_old_delivery": first_index + 1 if first_index is not None else None,
        "tools_after_old_delivery": len(post) if old else None,
        "fresh_prepare_after_old_delivery": sum(call["name"] == "prepare_read" for call in post),
        "tools": [call["name"] for call in tool_calls],
        "http_statuses": row["http_statuses"],
    }


def replay_check():
    for case_id, expected in DESIGN["cases"].items():
        for arm in DESIGN["arms"]:
            workflow = ReturnWorkflow(fixture(case_id), arm, RULES)
            workflow.status()
            workflow.select_plan(["bank"])
            preparation = workflow.prepare_read("bank")
            result = workflow.call("read_fields", preparation)
            allowed = "values" in result
            expected_native = expected["reuse"] and not (
                arm == "contract" and case_id == "temporary_priority_return"
            )
            assert allowed == expected_native, (case_id, arm, result)
            target = expected["target"]
            if not allowed:
                workflow.status()
                workflow.select_plan([target])
                preparation = workflow.prepare_read(target)
                result = workflow.read_fields(**preparation)
            workflow.confirm(target)
            workflow.execute(target, result["values"])
            assert workflow.commits == [target]
    print("10 scripted checks passed, including expected old-read decision and a single valid commit", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, default=HERE / "results.jsonl")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.verify:
        replay_check()
        return
    gateway = Gateway(os.environ["GAIA_MAAS_URL"], os.environ["GAIA_MAAS_DEV_KEY"])
    jobs = [
        (case_id, arm, seed)
        for i, case_id in enumerate(DESIGN["cases"])
        for j, seed in enumerate(DESIGN["seeds"])
        for arm in DESIGN["arms"][(i+j) % 2:] + DESIGN["arms"][:(i+j) % 2]
    ]

    def execute(job):
        case_id, arm, seed = job
        return score(case_id, run_business_episode(case_id, arm, seed, gateway))

    with args.output.open("a+", buffering=1) as output:
        output.seek(0)
        seen = {(r["case"], r["arm"], r["seed"]) for r in map(json.loads, output)}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute, job) for job in jobs if job not in seen]
            for future in as_completed(futures):
                record = future.result()
                output.write(json.dumps(record) + "\n")
                print({k: v for k, v in record.items() if k != "tools"}, flush=True)


if __name__ == "__main__":
    main()
