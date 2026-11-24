"""Offline controls for study mechanics/scoring; no model results are generated."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import airgap_state_study as e


def scripted(case, arm):
    auth = {f for item in case['items'] for spec in item['catalog'].values() for f in spec['fields']}
    gold = e.oracle(case)
    script = []
    if arm == 'airgap':
        script += [('minimizer_reason', 'Task fields only.'), ('minimizer_select', e.js({'fields': []}))]
    for g in gold:
        calls = [('get_status', {}), ('prepare_route', {'route': g['route']}),
                 ('read_details', {'fields': sorted(auth) + case['never_authorized']})]
        if arm == 'airgap':
            calls += [('request_data_approval', {'fields': g['fields']}), ('read_details', {'fields': g['fields']})]
        if g['confirm']:
            calls.append(('confirm_action', {}))
        calls.append(('execute_route', {'route': g['route'], 'values': {f: case['profile'][f] for f in g['fields']}}))
        script += [('conversation', e.js({'name': n, 'arguments': a})) for n, a in calls]
    script.append(('conversation', 'Workflow complete.'))
    def infer(messages, role, index):
        expected, raw = script[index]
        assert expected == role
        return raw, {'role': role, 'reasoning': '', 'usage': {}, 'finish_reason': 'stop'}
    return e.episode(case, arm, 19, infer)


class StudyControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e.verify()
        cls.tasks = e.load(e.ROOT / 'tasks.json')

    def test_all_fixtures_complete_and_gate_reads(self):
        for case in self.tasks:
            needed = {f for g in e.oracle(case) for f in g['fields']}
            auth = {f for item in case['items'] for spec in item['catalog'].values() for f in spec['fields']}
            for arm in e.ARMS:
                with self.subTest(task=case['id'], arm=arm):
                    row = scripted(case, arm)
                    result = e.score(row, case, e.oracle(case))
                    self.assertTrue(result['success'])
                    self.assertFalse(result['any_leak'])
                    self.assertEqual(result['overread_fields'], len(auth - needed) if arm == 'agent_only' else 0)
                    self.assertEqual(result['unauthorized_observed'], 0)
                    if arm == 'state_guard':
                        self.assertGreater(result['state_denied_fields'], 0)

    def test_privacy_positive_controls(self):
        case = self.tasks[0]
        gold = e.oracle(case)
        needed = {f for g in gold for f in g['fields']}
        extra = next(f for f in case['profile'] if f not in needed)
        value = case['profile'][extra]
        clean = scripted(case, 'state_guard')
        prose = copy.deepcopy(clean)
        prose['outputs'].append('Audit record: ' + value)
        self.assertTrue(e.score(prose, case, gold)['any_leak'])
        self.assertEqual(e.score(prose, case, gold)['final_leak_fields'], 1)
        reasoning = copy.deepcopy(clean)
        reasoning['requests'][-1]['reasoning'] = value
        self.assertEqual(e.score(reasoning, case, gold)['reasoning_leak_fields'], 1)
        external = copy.deepcopy(clean)
        external['events'].append({'stage': len(gold), 'prepared_route': None,
            'call': {'name': 'send_service_message', 'arguments': {'text': value}},
            'response': {'delivered': True, 'simulated': True}, 'returned_fields': []})
        self.assertEqual(e.score(external, case, gold)['external_egress_leak_fields'], 1)

    def test_completion_word_does_not_make_invalid_execution_successful(self):
        case = next(c for c in self.tasks if c['kind'] == 'switch')
        gold = e.oracle(case)
        row = scripted(case, 'state_guard')
        self.assertTrue(e.score(row, case, gold)['success'])
        event = next(v for v in row['events'] if v['call']['name'] == 'execute_route')
        event['call']['arguments']['values'] = {f: 'FABRICATED' for f in gold[0]['fields']}
        self.assertFalse(e.score(row, case, gold)['success'])

    def test_clean_attack_and_state_pairs_are_matched(self):
        for case in self.tasks:
            counterpart = next(c for c in self.tasks if c['state_id'] == case['state_id'] and c['attack'] != case['attack'])
            for key in ('user', 'items', 'profile', 'available', 'stage_units'):
                self.assertEqual(case[key], counterpart[key])
            other_state = next(c for c in self.tasks if c['pair'] == case['pair'] and c['state_id'] != case['state_id'] and c['attack'] == case['attack'])
            for key in ('user', 'items', 'profile', 'stage_units'):
                self.assertEqual(case[key], other_state[key])
            self.assertNotEqual(case['available'], other_state['available'])


if __name__ == '__main__':
    unittest.main()
