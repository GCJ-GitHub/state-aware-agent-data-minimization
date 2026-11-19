"""Verify published bytes and independently recompute the final headline table."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publication import REPO,verify_snapshot

verify_snapshot()
import state_holdout_cross_model as experiment
root=REPO/'state-holdout-cross-model'
cases={c['id']:c for c in json.loads((root/'tasks.json').read_text())}
gold=json.loads((root/'gold.json').read_text())
summary=json.loads((root/'summary.json').read_text())
metrics=('success','extra_fields','tool_calls','model_calls','confirmation_calls','unused_prose_cases','unused_execution_cases')
for model in ('local-qwen3-1.7b','qwen3.8-flash'):
    rows=[json.loads(line) for line in (root/(model+'.jsonl')).read_text().splitlines()]
    assert len(rows)==1080
    expected={(cid,arm,seed) for cid in cases for arm in experiment.ARMS for seed in experiment.SEEDS}
    assert {(r['id'],r['arm'],r['seed']) for r in rows}==expected
    for arm in experiment.ARMS:
        values=[experiment.score(r,cases[r['id']],gold[r['id']]) for r in rows if r['arm']==arm]
        computed={m:sum(v[m] for v in values) for m in metrics}
        assert all(computed[m]==summary[model]['groups'][arm][m] for m in metrics)
        print(model,arm,computed)
print('PUBLICATION_AND_HEADLINE_RESULTS_VERIFIED')
