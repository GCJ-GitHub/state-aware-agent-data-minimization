"""Offline fixtures for the 2x2 runner; these are not model experiment results."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import necessity_factorial as e


def scripted(case, arm):
    cache, approved = {}, set()
    last = None
    pending = None
    def emit(name, args):
        nonlocal last
        last = {'name': name, 'arguments': args}
        return e.io.js(last), {'role': 'conversation', 'reasoning': '', 'usage': {}, 'finish_reason': 'stop'}
    def use_values(response):
        session = response['sessions'][-1]
        action = next(a for a in session['enabled_actions'] if a['action'] == pending['action'])
        key = (session['session'], action['action'])
        if action['confirmation_required'] and key not in approved:
            return emit('confirm_action', {'session': key[0], 'action': key[1]})
        return emit('execute', {'session': key[0], 'action': key[1],
                               'values': {f: cache[f] for f in action['input_fields']}})
    def infer(messages, role, index):
        nonlocal pending
        if index == 0:
            return emit('inspect', {})
        response = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        previous = dict(last)
        if response.get('values'):
            cache.update(response['values'])
        if response.get('approved'):
            approved.add((previous['arguments']['session'], previous['arguments']['action']))
        if response['workflow_complete']:
            return 'Workflow complete.', {'role': 'conversation', 'reasoning': '', 'usage': {}, 'finish_reason': 'stop'}
        if response.get('refresh_public_state'):
            return emit('refresh_state', {})
        sessions = response.get('sessions', [])
        active = sessions[-1] if sessions else None
        if active and active['session_stale']:
            if previous['name'] == 'refresh_state' and response['status'] == 'ready':
                return emit('propose_plan', {'nodes': response['plans'][0]['nodes']})
            return emit('refresh_state', {})
        if response['status'] == 'need_evidence':
            return emit('probe', {'name': response['recommended_probe']})
        if previous['name'] == 'issue_read':
            if response['fields']:
                return emit('read_details', {'grant': response['grant'], 'fields': response['fields']})
            return use_values(response)
        if previous['name'] in ('read_details', 'confirm_action') and not response.get('error'):
            return use_values(response)
        if active and active['enabled_actions']:
            action = active['enabled_actions'][0]['action']
            pending = {'session': active['session'], 'action': action}
            return emit('issue_read', pending)
        return emit('propose_plan', {'nodes': response['plans'][0]['nodes']})
    return e.episode(case, arm, 19, infer)


class FactorialControls(unittest.TestCase):
    def test_only_complete_json_with_narrow_suffix_is_accepted(self):
        call = '{"name":"probe","arguments":{"name":"check_fee"}}'
        for suffix in ('', '\n</', '</tool_call>'):
            self.assertEqual(e.parse(call + suffix)['name'], 'probe')
        for raw in ('0', 'null', '[]', '{"name":"probe"}', call + ' arbitrary text', call[:-1]):
            self.assertIsNone(e.parse(raw))

    def test_common_manifests_and_messages_before_read_intervention(self):
        case = e.build_cases()[6]
        a, b = e.Backend(case, 'fixed_soft'), e.Backend(case, 'fixed_enforced')
        self.assertEqual(e.manifest(a.v, case), e.manifest(b.v, case))
        self.assertEqual(a.info(), b.info())

    def test_all_48_fixture_workflows_complete_with_scripted_calls(self):
        count = 0
        for case in e.build_cases():
            for arm in e.ARMS:
                with self.subTest(case=case['id'], arm=arm):
                    row = scripted(case, arm)
                    result = e.score(row, case)
                    self.assertTrue(result['task_success'])
                    self.assertFalse(result['any_leak'])
                    if arm.endswith('enforced'):
                        self.assertEqual(result['outside_justification_fields'], 0)
                    if case['family'] == 'evidence_drift':
                        if arm.endswith('enforced'):
                            self.assertEqual(result['blocked_reads'], 1)
                            self.assertTrue(result['success_after_block'])
                        else:
                            self.assertEqual(result['expired_evidence_fields'], 2)
                    count += 1
        self.assertEqual(count, 48)

    def test_public_contracts_do_not_contain_private_values(self):
        for case in e.build_cases():
            v = e.make_verifier(case)
            public = e.io.js(e.manifest(v, case)) + e.user_text(case) + e.SYSTEM
            for f, value in v.authority._values.items():
                self.assertNotIn(str(value), public, f)

    def test_independent_oracle_agrees_on_initial_supported_plans(self):
        for case in e.build_cases():
            v = e.make_verifier(case)
            alternatives = e.truth_plan_oracle(v, e.actual_facts(v))
            self.assertTrue(alternatives)
            # All currently verified plans satisfy actual hidden truth, although
            # initially unknown predicates can delay giving any plan to the agent.
            for p in v.frontier()['accepted_plans']:
                self.assertIn(set(p.nodes), [a['nodes'] for a in alternatives])


if __name__ == '__main__':
    unittest.main()
