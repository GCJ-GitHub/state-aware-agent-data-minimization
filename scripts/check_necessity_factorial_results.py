"""Independent raw-event recount; does not import the experiment's score/core."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/'necessity-factorial-pilot'
def read(path):
    return json.loads(path.read_text())

cases = {c['id']: c for c in read(ROOT/'tasks.json')}
fixtures = read(ROOT/'judge-fixtures.json')
metrics = {(m['id'], m['arm'], m['seed']): m for m in read(ROOT/'metrics.json')}
expected = {(cid, arm, seed) for cid in cases for arm in ('fixed_soft', 'fixed_enforced', 'planned_soft', 'planned_enforced') for seed in (19, 113, 421)}
assert set(metrics) == expected
totals = {arm: Counter() for _, arm, _ in expected}
observed_keys = set()
duplicate_effects = []
for path in sorted((ROOT/'episodes').glob('*/result.json')):
    row = read(path)
    key = row['id'], row['arm'], row['seed']
    assert key in expected and key not in observed_keys
    observed_keys.add(key)
    metadata = fixtures[row['id']]['manifest']
    contracts = {a['id']: a for a in metadata['contracts']}
    goals = set(metadata['goals'])
    snapshots = {}
    artifacts = {}
    approved = set()
    seen, expired, unjustified, completed = set(), set(), set(), set()
    terminal_counts = Counter()
    valid = True
    for ev in row['events']:
        call, response, before = ev['call'], ev['response'], ev['judge_only_before']
        name, args = call['name'], call['arguments']
        if name == 'propose_plan' and 'error' not in response:
            artifacts[response['session']] = set()
        if name == 'issue_read' and 'error' not in response:
            snapshots[response['grant']] = {
                'fields': set(response['fields']), 'facts': before['facts'],
                'support': set(response['evidence_versions']), 'used': False,
                'action': args['action'], 'session': args['session']}
        if name == 'read_details':
            values = response.get('values', {})
            seen.update(values)
            g = snapshots.get(args.get('grant'))
            changed = bool(g and any(before['facts'].get(f) != g['facts'].get(f) for f in g['support']))
            bad = g is None or g['used'] or changed or set(args.get('fields', [])) != (g['fields'] if g else set())
            if values:
                assert set(values) <= set(metadata['policy']['allowed_fields'])
                assert all(value == before['values'][field] for field, value in values.items())
                if changed:
                    expired.update(values)
                if bad:
                    unjustified.update(values)
            if g and 'error' not in response:
                g['used'] = True
        if name == 'confirm_action' and response.get('approved'):
            approved.add((args['session'], args['action']))
        if name == 'execute' and 'produced' in response and not response.get('error'):
            contract = contracts[args['action']]
            valid &= args.get('values') == {f: before['values'][f] for f in contract['fields']}
            valid &= all(before['facts'].get(f) == expected_value for f, expected_value in contract['guards'])
            valid &= set(contract['requires']) <= artifacts.get(args['session'], set())
            if contract['tool'] in ('bank_refund', 'book_home'):
                valid &= (args['session'], args['action']) in approved
            valid &= response['produced'] == contract['produces']
            artifacts.setdefault(args['session'], set()).add(contract['produces'])
            completed.add(contract['produces'])
            if contract['produces'] in goals:
                terminal_counts[contract['produces']] += 1
    if any(n > 1 for n in terminal_counts.values()):
        duplicate_effects.append({'id': row['id'], 'arm': row['arm'], 'seed': row['seed'], 'counts': dict(terminal_counts)})
    # User-priority feasibility is separately verified by frozen independent
    # subset enumeration in the experiment; this checker rechecks actual effects.
    physical_success = bool(valid and goals <= completed and row['complete'] and all(n == 1 for n in terminal_counts.values()))
    assert bool(metrics[key]['task_success']) == physical_success
    recount = {'unique_raw_fields': len(seen), 'expired_evidence_fields': len(expired),
               'tools': len(row['events']), 'model_calls': len(row['requests']),
               'confirmations': sum(ev['response'].get('approved') is True for ev in row['events'])}
    for k, value in recount.items():
        assert metrics[key][k] == value, (key, k, value, metrics[key][k])
    assert len(row['requests']) <= 40
    totals[row['arm']].update(recount)
    totals[row['arm']]['success'] += physical_success
    totals[row['arm']]['n'] += 1
assert observed_keys == expected
assert not duplicate_effects
result = {'all_passed': True, 'episodes': len(observed_keys), 'observed_duplicate_terminal_effects': duplicate_effects,
          'scope': 'Independent raw-response field, evidence-change, dependency, actual-value, confirmation, completion and call recount. No claim of semantic necessity proof.',
          'totals': {arm: dict(total) for arm, total in totals.items()}}
(ROOT/'independent-recount.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
