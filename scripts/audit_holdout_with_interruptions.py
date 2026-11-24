"""Lossless offline prefix reconstruction + replay; NEVER calls a model API.

Frozen runner can stop at an HTTP error before writing result.json. Reconstruct
only observed cached returns using the exact same loop with an offline replay
boundary. Do not fabricate a return, action, final response or extra budget.
"""
import json,sys,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import necessity_holdout as h
h.verify()
cases={c['id']:c for c in h.io.load(h.ROOT/'tasks.json')}
only='--reconstruct-http400-only' in sys.argv
total=0;episodes=0;prefixes=[]
for directory in sorted((h.ROOT/'episodes').iterdir()):
    if not directory.is_dir():continue
    result=directory/'result.json';interrupt=directory/'interruption.json'
    if only and (result.exists() or not interrupt.exists() or h.io.load(interrupt).get('category')!='HTTP_400'):continue
    if not result.exists() and not interrupt.exists():raise RuntimeError('Run still in progress')
    records=[h.io.load(p) for p in sorted(directory.glob('[0-9][0-9].json'))]
    if not records:raise RuntimeError('No observed response prefix; retain as infrastructure failure explicitly')
    if result.exists():
        row=h.io.load(result);cid,arm,seed=row['id'],row['arm'],row['seed']
        terminal=row.get('terminal_transport_error')
    else:
        cid,arm,seedstr=directory.name.rsplit('__',2);seed=int(seedstr)
        terminal=h.io.load(interrupt)
        assert terminal['category']=='HTTP_400',terminal
        row=None
    def replay(messages,index):
        assert index<len(records),'No synthetic model return permitted'
        record=records[index];body=h.native.request_body(messages,seed)
        assert record['request_body']==body and record['request_sha256']==h.io.sha(h.io.js(body))
        return record['native_message'],record['meta']
    loop=h.episode
    if terminal:
        globals_copy=dict(loop.__globals__);globals_copy['LIMIT']=len(records)
        loop=types.FunctionType(loop.__code__,globals_copy,'offline_observed_prefix')
    captured={}
    if terminal:
        def capture(frame,event,arg):
            if event=='return' and frame.f_code is loop.__code__:
                captured['messages']=frame.f_locals['messages']
        sys.setprofile(capture)
    try:
        actual=loop(cases[cid],arm,seed,replay)
    finally:
        sys.setprofile(None)
    if terminal:
        # Reconstruct the last failed request from deterministic state, not an API replay.
        body=h.native.request_body(captured['messages'],seed)
        h.io.dump(directory/'failed-request-reconstructed.json',{'note':'Reconstructed failed HTTP request, no response fabricated and no API call performed. Error body was not retained by original frozen transport.','request_body':body,'request_sha256':h.io.sha(h.io.js(body))})
        actual['terminal_transport_error']=terminal
        actual['prefix_reconstruction']={'observed_model_returns':len(records),'formal_model_return_limit':40,'offline_replay_boundary_only':True,'synthetic_model_returns':0}
        prefixes.append({'id':cid,'arm':arm,'seed':seed,'observed_returns':len(records),'business_complete':actual['complete'],'error':terminal['category']})
    if row is None:h.io.dump(result,actual)
    else:assert actual==row,directory.name
    total+=len(records);episodes+=1
out={'all_passed':True,'episodes':episodes,'model_inputs':total,'full_native_request_body_replayed':True,'interrupted_observed_prefixes':prefixes,'fabricated_returns':0,'model_api_calls_during_audit':0}
h.io.dump(h.ROOT/('interrupted-prefix-audit.json' if only else 'audit.json'),out)
print(json.dumps(out))
