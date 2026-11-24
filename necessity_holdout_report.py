"""Fixed paired-cluster descriptive analysis, no model calls."""
import json,random
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'necessity-three-arm-holdout'
load=lambda p:json.loads(p.read_text())
rows=load(ROOT/'metrics.json');summary=load(ROOT/'summary.json');cases={c['id']:c for c in load(ROOT/'tasks.json')}
clusters=sorted({r['pair'] for r in rows});arms=('upfront','agent_only','state_guard')
keys=('task_success','unique_raw_fields','hindsight_unused_fields','premature_fields','expired_evidence_fields','tools','model_calls','confirmations','any_leak')
assert len(rows)==1080 and all(summary['tables']['all'][a]['n']==360 for a in arms)
means={(p,a,k):sum(float(r[k]) for r in rows if r['pair']==p and r['arm']==a)/6 for p in clusters for a in arms for k in keys}
rng=random.Random(202611238903);draws=[[rng.choice(clusters) for _ in clusters] for _ in range(5000)]
contrasts={}
for other in ('upfront','agent_only'):
    contrasts[other]={}
    for k in keys:
        delta={p:means[p,'state_guard',k]-means[p,other,k] for p in clusters}
        boots=sorted(sum(delta[p] for p in sample)/len(sample) for sample in draws)
        contrasts[other][k]={'delta_per_episode':sum(delta.values())/len(delta),'ci95':[boots[124],boots[4874]]}
triggers=Counter();families=Counter();bad=[]
for p in (ROOT/'episodes').glob('*/result.json'):
    r=load(p)
    if r['family']=='switch':
        families[r['arm']]+=1
        if r['environment_events']:triggers[r['arm']]+=1
    m=next(m for m in rows if (m['id'],m['arm'],m['seed'])==(r['id'],r['arm'],r['seed']))
    if not m['task_success']:bad.append({'id':r['id'],'arm':r['arm'],'seed':r['seed'],'tools':m['tools'],'protocol_errors':m['native_protocol_errors']})
analysis={'unit':'60 state-pair clusters, both members and 3 seeds nested','bootstrap_samples':5000,'contrasts_state_guard_minus':contrasts,'switch_event_triggered':dict(triggers),'switch_denominators':dict(families),'failures':bad}
(ROOT/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
lines=['# 冻结三组新任务结果','', '同一 MaaS qwen3.8-flash，120 题 / 60 状态对，三组各重复三次，共 1080 次。所有正式尝试保留。','',
'| 方案 | 成功 | 唯一原值字段累计 | 事后未用字段 | 提前字段 | 过期字段 | 工具 | 模型 | 确认 | 有泄露轨迹 |',
'|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
labels={'upfront':'事前给齐','agent_only':'自行按需','state_guard':'后端按状态校验'}
for a in arms:
    t=summary['tables']['all'][a]
    lines.append(f"| {labels[a]} | {t['task_success']}/{t['n']} | "+' | '.join(str(t[k]) for k in ('unique_raw_fields','hindsight_unused_fields','premature_fields','expired_evidence_fields','tools','model_calls','confirmations','any_leak'))+' |')
lines +=['','## 分场景','']
for family in ('single','switch','multi'):
    lines +=[f'### {family}','','| 方案 | 成功 | 未用字段 | 过期字段 | 工具 | 拦截 | 拦截后成功轨迹 |','|---|---:|---:|---:|---:|---:|---:|']
    for a in arms:
        t=summary['tables'][family][a]
        lines.append(f"| {labels[a]} | {t['task_success']}/{t['n']} | "+' | '.join(str(t[k]) for k in ('hindsight_unused_fields','expired_evidence_fields','tools','blocked_reads','success_after_block'))+' |')
lines +=['','## 配对差值与区间','','以下为后端组减对照组，每条任务尝试的平均差；95% 区间按 60 状态对聚类 bootstrap 5000 次。同对两成员与三个重复不视为独立样本。','', '| 对照 | 指标 | 平均差 | 95% 区间 |','|---|---|---:|---|']
for a,vs in contrasts.items():
    for k,m in vs.items():lines.append(f"| {labels[a]} | {k} | {m['delta_per_episode']:.4f} | [{m['ci95'][0]:.4f}, {m['ci95'][1]:.4f}] |")
lines +=['','## 触发、成本与证据边界','',f'状态变化任务各组 {dict(families)} 条，实际触发状态事件 {dict(triggers)}。事件发生在首个 read grant 返回后；有已知值而省略 issue_read 的轨迹可能不触发。若触发率不同，事前组与按需组在动态任务上的差值不能全部归因于校验。',
 f"HTTP 请求尝试 {summary['http_attempts']}，错误 {summary['http_errors']}；含最初受限网络启动错误，重试不计模型返回次数。",
 '初始字段在真实 inspect 的 values 工具回包中交付。事前给齐是放行时机基线，不是完整 AirGapAgent 复现。',
 '本轮冻结了业务规则和提示后才开始正式模型调用；没有按正式错误调规则或只重跑失败题。任务仍是设计者生成的参数化合成题，并非第三方盲测或真实生产分布。',
 '提前、过期和事后未用是不同口径，有重叠，不能相加当泄露。事后未用会受任务失败影响。',
 '所有可见模型文本和模拟外发检查完整合成值；零匹配不能证明隐藏推理、部分值或改写泄露安全。',
 '确认由确定性模拟用户完成，不能解释为真实用户体验改善。模型名是供应方别名，不是权重版本。',
 '相关性与代码正确性检查：audit.json 完整请求重放；independent-recount.json 独立事件重算；freeze.json 规则指纹。',
 '', '## 失败轨迹','',json.dumps(bad,ensure_ascii=False,indent=2)]
(ROOT/'REPORT.md').write_text('\n'.join(lines)+'\n')
print('REPORT_WRITTEN',len(rows))
