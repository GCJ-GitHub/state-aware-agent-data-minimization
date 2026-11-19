"""Run the frozen latest tasks into a separate, ignored output directory."""
import argparse
import importlib
import os
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publication import REPO,verify_snapshot

p=argparse.ArgumentParser()
p.add_argument('--model',required=True,choices=['local-qwen3-1.7b','qwen3.8-flash'])
p.add_argument('--out',required=True,type=Path)
p.add_argument('--key-file',type=Path)
a=p.parse_args()
verify_snapshot()
source=REPO/'state-holdout-cross-model';out=a.out.resolve()
if out==source:raise SystemExit('Use a separate runs/ directory; archived results are immutable.')
out.mkdir(parents=True,exist_ok=True)
for name in ('tasks.json','gold.json','canonical-system.txt','protocol.json','self-check.json','maas-preflight.json'):
    target=out/name
    if target.exists():
        if target.read_bytes()!=(source/name).read_bytes():raise SystemExit('Existing input differs: '+name)
    else:shutil.copyfile(source/name,target)
if a.model=='qwen3.8-flash' and not a.key_file:raise SystemExit('Pass a key file stored outside this repository.')
if a.model=='qwen3.8-flash' and not os.environ.get('QWEN_MAAS_URL'):raise SystemExit('Set QWEN_MAAS_URL externally before inference.')
experiment=importlib.import_module('state_holdout_cross_model')
experiment.ROOT=out
experiment.run(a.model,str(a.key_file) if a.key_file else None)
