"""Independent state-transition and treatment-fidelity checks, no model calls."""
import json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'necessity-three-arm-holdout'
load=lambda p:json.loads(p.read_text())
cases={c['id']:c for c in load(ROOT/'tasks.json')}
counts={a:Counter() for a in ('upfront','agent_only','state_guard')}
for p in sorted((ROOT/'episodes').glob('*/result.json')):
    row=load(p);case=cases[row['id']];arm=row['arm'];counts[arm]['episodes']+=1
    facts=case['facts'];changed=False;initial_delivery=False;first_plan=False
    initial=load(p.parent/'00.json')['request_body']['messages']
    for value in case['values'].values():assert value not in json.dumps(initial),'raw value in initial prompt'
    for i,e in enumerate(row['events']):
        assert e['judge_only_before']['facts']==facts,(case['id'],arm,'state ledger mismatch',i)
        if e['call']['name']=='propose_plan':first_plan=True
        if e['details'].get('upfront_delivery'):
            assert not initial_delivery;initial_delivery=True
            expected=set(case['values']) if arm=='upfront' else set()
            assert set(e['response']['values'])==expected
            if not first_plan:counts[arm]['initial_delivery_before_plan']+=1
        if case['family']=='switch' and e['call']['name']=='issue_read' and e['response'].get('grant') and not changed:
            facts=case['after_facts'];changed=True
    assert bool(row['environment_events'])==changed
    if changed:
        assert len(row['environment_events'])==1
        assert row['environment_events'][0]['before']==case['facts']
        assert row['environment_events'][0]['after']==case['after_facts']
    counts[arm]['first_tool_inspect']+=bool(row['events'] and row['events'][0]['call']['name']=='inspect')
    counts[arm]['initial_delivery_observed']+=initial_delivery
    if case['family']=='switch':counts[arm]['switch_episodes']+=1;counts[arm]['switch_triggered']+=changed
out={'all_passed':True,'note':'Trigger proportions are observed treatment fidelity, not forced equal. No experimental rule edits.','by_arm':{a:dict(c) for a,c in counts.items()}}
(ROOT/'state-ledger-audit.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))
