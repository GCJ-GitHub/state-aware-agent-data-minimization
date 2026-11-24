"""Post-hoc completion diagnostics, explicitly separate from frozen primary score."""
import json,statistics
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'necessity-three-arm-holdout'
load=lambda p:json.loads(p.read_text())
rows=[load(p) for p in sorted((ROOT/'episodes').glob('*/result.json'))]
assert len(rows)==1080
out={};bad=[];versions=Counter()
for arm in ('upfront','agent_only','state_guard'):
    part=[r for r in rows if r['arm']==arm];clean=0;post=0
    for r in part:
        last=r['native_messages'][-1] if r['native_messages'] else {}
        good=bool(r['complete'] and not last.get('tool_calls') and (last.get('content') or '').strip() and not r.get('terminal_transport_error'))
        clean+=good
        if not good:bad.append({'id':r['id'],'arm':arm,'seed':r['seed'],'business_complete':r['complete'],'terminal_transport_error':r.get('terminal_transport_error')})
        completed=False
        for e in r['events']:
            post+=completed
            completed=completed or bool(e['response'].get('workflow_complete'))
        versions.update(str(m.get('model_version')) for m in r['requests'])
    tools=sorted(len(r['events']) for r in part);models=sorted(len(r['requests']) for r in part)
    out[arm]={'n':len(part),'normal_final_response':clean,'post_completion_tool_calls':post,
              'tools_median':statistics.median(tools),'tools_p95':tools[int(.95*(len(tools)-1))],
              'model_calls_median':statistics.median(models),'model_calls_p95':models[int(.95*(len(models)-1))]}
result={'note':'Post-hoc diagnostic; frozen task_success means valid business goals completed and does not require a final text response. Do not silently substitute the endpoint. All recorded calls including post-completion loops retained.','by_arm':out,'non_normal_terminations':bad,'reported_model_versions':dict(versions)}
(ROOT/'completion-diagnostics.json').write_text(json.dumps(result,indent=2)+'\n')
fidelity=load(ROOT/'state-ledger-audit.json')
lines=['','## 正常收尾与测量限制（补充诊断）','',result['note'],'','| 组 | 正常最终回答 | 业务完成后工具调用 | 工具中位数 / P95 | 模型调用中位数 / P95 |','|---|---:|---:|---|---|']
for arm,t in out.items():lines.append(f"| {arm} | {t['normal_final_response']}/{t['n']} | {t['post_completion_tool_calls']} | {t['tools_median']} / {t['tools_p95']} | {t['model_calls_median']} / {t['model_calls_p95']} |")
lines +=['', '异常收尾：'+json.dumps(bad,ensure_ascii=False),
 'HTTP 400 没有保留服务错误正文，因此不猜测供应方拒绝的具体原因。离线恢复只重放已缓存的实际回复；没有补模型回复、补执行或增加预算。原中断文件保留。',
 '若成功率/泄露率在所有观察中相同，经验 bootstrap 区间可能退化成 [0,0]，这不表示真实差异必为零，也不证明生产风险为零。',
 '模型报告版本：'+json.dumps(dict(versions),ensure_ascii=False),
 '状态与呈现核验：'+json.dumps(fidelity['by_arm'],ensure_ascii=False),
 '主要因果对比仍为后端按状态校验 vs 自行按需。事前组若因已有字段跳过 issue_read，会少触发动态事件；不能把该组动态子集的全部差值归因于放行时机。',
 '复核命令：python3 scripts/audit_holdout_with_interruptions.py；python3 necessity_holdout.py summarize；python3 scripts/check_necessity_holdout_results.py；python3 scripts/check_holdout_state_ledger.py；python3 necessity_holdout_report.py；python3 scripts/describe_holdout_completion.py。',
 '上面的补充诊断在运行过程中观察到异常后添加，不是事前注册的新主要终点。']
with (ROOT/'REPORT.md').open('a') as f:f.write('\n'.join(lines)+'\n')
print(json.dumps(result))
