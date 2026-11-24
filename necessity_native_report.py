"""Offline, all-attempt analysis for the native interface repair diagnostic."""
import json
import random
from collections import Counter
import necessity_native_retest as n

LABELS={'fixed_soft':'固定建议／取数不强制','fixed_enforced':'固定建议／强制验证',
        'planned_soft':'规划建议／取数不强制','planned_enforced':'规划建议／强制验证'}


def latest_feedback(messages):
    last=messages[-1]
    text=last.get('content') or ''
    if last['role']=='tool':
        return json.loads(text)
    prefix='Initial trusted task metadata and planning observation:\n'
    if text.startswith(prefix):
        return json.loads(text[len(prefix):])['initial_planning']
    if 'Current feedback: ' in text:
        return json.loads(text.split('Current feedback: ',1)[1])
    return {}


def analyze():
    n.verify()
    summary=n.io.load(n.ROOT/'summary.json')
    audit=n.io.load(n.ROOT/'audit.json')
    metrics=n.io.load(n.ROOT/'metrics.json')
    assert len(metrics)==144 and audit['episodes']==144 and audit['all_passed']
    cases={c['id']:c for c in n.io.load(n.ROOT/'tasks.json')}
    old_summary=n.io.load(n.old.ROOT/'summary.json')
    old_metrics=n.io.load(n.old.ROOT/'metrics.json')
    assert (n.ROOT/'tasks.json').read_bytes()==(n.old.ROOT/'tasks.json').read_bytes()
    index={(m['id'],m['arm'],m['seed']):m for m in metrics}
    prior={(m['id'],m['arm'],m['seed']):m for m in old_metrics}
    assert set(index)==set(prior) and len(index)==144
    visible={a:Counter() for a in n.ARMS}
    failures=[]
    http={a:Counter() for a in n.ARMS}
    drift_traces=[]
    for path in sorted((n.ROOT/'episodes').glob('*/result.json')):
        row=n.io.load(path)
        metric=index[row['id'],row['arm'],row['seed']]
        if not metric['task_success']:
            failures.append({'id':row['id'],'arm':row['arm'],'seed':row['seed'],
                              'model_calls':len(row['requests']),'tools':len(row['events']),
                              'protocol_errors':row['native_protocol_errors']})
        event_index=0
        for turn,message in enumerate(row['native_messages']):
            call,error=n.decode_native(message)
            if not call:
                continue
            event=row['events'][event_index];event_index+=1
            if call['name']!='probe' or event['response'].get('error'):
                continue
            cache=n.io.load(path.parent/f'{turn:02d}.json')
            feedback=latest_feedback(cache['messages'])
            hint=feedback.get('recommended_probe')
            visible[row['arm']]['successful_queries']+=1
            if hint is not None:
                visible[row['arm']]['had_visible_hint']+=1
                visible[row['arm']]['matched_visible_hint']+=call['arguments'].get('name')==hint
            elif feedback.get('status')=='ready':
                visible[row['arm']]['queried_when_plan_ready']+=1
            else:
                visible[row['arm']]['other_without_hint']+=1
        if row['family']=='evidence_drift' and row['seed']==19:
            drift_traces.append({'id':row['id'],'arm':row['arm'],'steps':[
                {'tool':e['call']['name'],'action':e['call']['arguments'].get('action'),
                 'returned_fields':e['details'].get('returned_fields',[]),
                 'read_verdict':e['details'].get('read_verdict'),'error':e['response'].get('error')}
                for e in row['events']]})
        for line in (path.parent/'http.jsonl').read_text().splitlines():
            attempt=json.loads(line)
            http[row['arm']]['attempts']+=1
            http[row['arm']]['ok' if attempt['ok'] else 'errors']+=1
    query_ids={cid for cid,c in cases.items() if n.old.make_verifier(c).authority.probes}
    query_subset={}
    for arm in n.ARMS:
        part=[m for m in metrics if m['arm']==arm and m['id'] in query_ids]
        query_subset[arm]={'n':len(part),'success':sum(m['task_success'] for m in part),
                           'queries':sum(m['predicate_queries'] for m in part),
                           'backend_reads':sum(m['backend_private_reads'] for m in part)}
    measures=('task_success','unique_raw_fields','expired_evidence_fields','predicate_queries','tools','model_calls')
    clusters=[]
    for cid in cases:
        differences=[]
        for seed in n.SEEDS:
            f0,f1,p0,p1=[index[cid,a,seed] for a in n.ARMS]
            differences.append({'query_advice':{k:((p0[k]-f0[k])+(p1[k]-f1[k]))/2 for k in measures},
                'read_enforcement':{k:((f1[k]-f0[k])+(p1[k]-p0[k]))/2 for k in measures}})
        clusters.append({factor:{k:sum(d[factor][k] for d in differences)/3 for k in measures}
                         for factor in differences[0]})
    rng=random.Random(20261123723)
    effects={}
    for factor in ('query_advice','read_enforcement'):
        samples={k:[] for k in measures}
        for _ in range(5000):
            draw=[rng.choice(clusters) for _ in clusters]
            for k in measures:samples[k].append(sum(c[factor][k] for c in draw)/len(draw))
        effects[factor]={k:{'difference_per_episode':sum(c[factor][k] for c in clusters)/len(clusters),
                            'ci95':[sorted(samples[k])[124],sorted(samples[k])[4874]]} for k in measures}
    n.io.dump(n.ROOT/'analysis.json',{'same_case_seed_arm_keys':144,'exact_task_bytes_unchanged':True,
        'visible_advice':{a:dict(v) for a,v in visible.items()},'query_subset':query_subset,
        'paired_task_cluster_effects':effects,'failures':failures,
        'http_by_arm':{a:dict(v) for a,v in http.items()}})
    n.io.dump(n.ROOT/'drift-example-traces.json',drift_traces)
    lines=['# 原生工具协议与建议呈现修复：同批四组对照','',
        '日期：2026-11-23。同一 MaaS `qwen3.8-flash`，上一轮同一批 12 任务×4组×3次，共144条。', '',
        '**这是已知任务的接口诊断重测，不是新的盲测或跨任务泛化。** 业务/取数规则未改；统一换原生 tools/tool_calls、首次提供规划状态和建议，并明确共同的就绪后停止查询指令。三项共同修复不能从跨轮差额中单独归因。','',
        '## 全量四组结果','',
        '| 组别 | 成功 | 不同原值字段次 | 过期依据读取字段次 | 判断查询 | 工具调用 | 模型调用 | 确认 | 原生协议错误 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm in n.ARMS:
        t=summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {t["task_success"]}/{t["n"]} | {t["unique_raw_fields"]} | {t["expired_evidence_fields"]} | {t["predicate_queries"]} | {t["tools"]} | {t["model_calls"]} | {t["confirmations"]} | {t["native_protocol_errors"]} |')
    lines+=['','全部尝试保留；原值字段按每条轨迹去重求和，不同指标可能重叠，不能相加。这里取数不强制仍有共同的授权、计划及实际执行检查。','',
        '## 与上一轮逐组比较','',
        '| 组别 | 成功：旧→新 | 判断查询：旧→新 | 工具调用：旧→新 | 模型调用：旧→新 |',
        '|---|---:|---:|---:|---:|']
    for arm in n.ARMS:
        a=old_summary['tables']['all'][arm];b=summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {a["task_success"]}→{b["task_success"]} /36 | {a["predicate_queries"]}→{b["predicate_queries"]} | {a["tools"]}→{b["tools"]} | {a["model_calls"]}→{b["model_calls"]} |')
    lines+=['','上一轮11条格式失败在执行任何业务工具前结束，成功数、实际工作量不同。总调用数跨轮变化不能单独解读为算法效率；本轮内部四组比较更适合判断建议与读取验证的作用。','',
        '## 建议实际呈现与执行','',
        '| 组别 | 有判断接口的子集轨迹 | 子集成功 | 判断查询 | 后端判断原始字段读取次 | 有可见建议的查询 | 符合可见建议 | 就绪后继续查询 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm in n.ARMS:
        q=query_subset[arm];v=visible[arm]
        lines.append(f'| {LABELS[arm]} | {q["n"]} | {q["success"]} | {q["queries"]} | {q["backend_reads"]} | {v["had_visible_hint"]} | {v["matched_visible_hint"]} | {v["queried_when_plan_ready"]} |')
    lines+=['','子集由运行前工具结构决定，含三个不同任务，不按结果筛选。建议仍可被模型忽略，查询没有由框架自动发起。规划使用已有的精确动态规划和设计者给定先验，不是新算法；固定顺序也会在计划已确定后停止建议。','',
        '## 预先指定的状态变化子集','',
        '| 组别 | 成功 | 不同原值字段次 | 过期依据读取字段次 | 实际拦截 | 拦截后成功 | 工具调用 | 模型调用 | 确认 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm in n.ARMS:
        t=summary['tables']['evidence_drift'][arm]
        lines.append(f'| {LABELS[arm]} | {t["task_success"]}/{t["n"]} | {t["unique_raw_fields"]} | {t["expired_evidence_fields"]} | {t["blocked_reads"]} | {t["success_after_block"]} | {t["tools"]} | {t["model_calls"]} | {t["confirmations"]} |')
    lines+=['','变化发生在首份读取凭据响应形成后、后续取数前，四组相同；模型自己根据反馈刷新证据、重选计划、取数及执行。只有两种预设变化，不代表真实漂移分布或并发原子性保证。','',
        '## 分别统计数据接触与泄露','',
        '| 组别 | 原值递送字段次 | 判断结果次 | 后端判断读取字段次 | 回答泄露字段次 | 模拟外发泄露字段次 | 可见推理调用数 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for arm in n.ARMS:
        t=summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {t["raw_disclosure_deliveries"]} | {t["predicate_results_released"]} | {t["backend_private_reads"]} | {t["prose_leak_fields"]} | {t["external_leak_fields"]} | {t["visible_reasoning_calls"]} |')
    lines+=['','模型少接触原值不意味着后端没读数据，判断结果也披露信息。所有原生响应的 content 均进入回答隐私检查，不因同时存在工具调用而被丢弃。只匹配完整合成引用/完整数值；明确要求的费用报告允许相应原值，未测试隐藏推理、部分值或语义推断。','',
        '## 按任务配对的不确定性','',
        '12个任务整体bootstrap 5,000次，保留四组和三个种子；查询效应=规划减固定，读取验证效应=强制减不强制，均对另一个因子取平均。只是当前已知任务的条件区间。','',
        '| 因子 | 指标 | 每轨迹平均差 | 95%区间 |','|---|---|---:|---|']
    for factor in effects:
        for k in measures:
            v=effects[factor][k]
            lines.append(f'| {factor} | {k} | {v["difference_per_episode"]:.4f} | [{v["ci95"][0]:.4f}, {v["ci95"][1]:.4f}] |')
    lines+=['','全成功或全不泄露会形成退化零差区间，这不证明未见任务的风险为零。三个查询任务及两个变化任务不足以支持宽泛统计主张。','',
        '## 传输成本与审计','',
        '| 组别 | prompt token | completion token | 截断调用 | 停顿恢复 | HTTP尝试 | HTTP错误 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for arm in n.ARMS:
        t=summary['tables']['all'][arm];h=http[arm]
        lines.append(f'| {LABELS[arm]} | {t["prompt_tokens"]} | {t["completion_tokens"]} | {t["truncated_calls"]} | {t["recoveries"]} | {h["attempts"]} | {h["errors"]} |')
    lines+=['',f'完整重放通过：{audit["episodes"]}条轨迹、{audit["model_inputs"]}次完整原生请求（含tools、参数和tool_call_id上下文）。HTTP错误：`{json.dumps(summary["http_errors"])}`。成功返回先落盘后执行，续跑不重生成成功步骤；开发与协议探测单列，不混入主表。','',
        '## 可以与不能得出的结论','',
        '- 可判断共同接口修复后，当前任务的自主执行可靠性、查询建议遵循和读前验证表现。',
        '- 可以在同批同预算下复查状态变化窗口，但不能称为新任务复现。',
        '- 查询的减少只适用于当前给定先验与诊断任务；动态规划不是本研究原创，尚无真实业务先验和扩展性证据。',
        '- 仍为合成工具、人工契约和小图规划；没有自然语言授权自动可靠编译、任意API理解、生产事务或端到端输出隔离。',
        '- 本轮没有AirGapAgent、CaMeL、CapAgent直接复现，不能据此声称优于这些工作或已达到论文SOTA。','',
        '## 复现','',
        '`protocol.json`、`freeze.json`、`native-tools.json`固定接口与规则；`tasks.json`和`judge-fixtures.json`与上一轮字节一致。原生完整请求体及返回在`episodes/*/NN.json`，业务事件在`result.json`。','',
        '```bash','python3 necessity_native_retest.py audit','python3 necessity_native_retest.py summarize','python3 scripts/check_necessity_native_results.py','python3 necessity_native_report.py','```','']
    totals=summary['tables']['all']
    fixed_q=sum(totals[a]['predicate_queries'] for a in n.ARMS if a.startswith('fixed'))
    planned_q=sum(totals[a]['predicate_queries'] for a in n.ARMS if a.startswith('planned'))
    hint_total=sum(v['had_visible_hint'] for v in visible.values())
    hint_matched=sum(v['matched_visible_hint'] for v in visible.values())
    q_total=sum(v['successful_queries'] for v in visible.values())
    lines+=['## 本轮归纳','',
        f'全量成功 {sum(t["task_success"] for t in totals.values())}/144；原生协议错误 {sum(t["native_protocol_errors"] for t in totals.values())}。上一轮为133/144，11条格式失败没有被删改，而是使用统一新接口完整重测。','',
        f'固定建议合计 {fixed_q} 次判断查询，规划建议 {planned_q} 次，相差 {fixed_q-planned_q} 次；在本设计诊断集上出现小幅节省，不能外推为真实业务平均节省。{q_total} 次成功查询均需结合实际输入审计：{hint_total} 次有非空可见建议，其中 {hint_matched} 次与建议一致。建议可见和实际遵循是两件事，接口修复不代表策略执行已完全闭环。','',
        '状态变化子集中的取数验证、任务恢复和开销以子集表为准，不把全部144条的差额都说成状态验证收益。未观察到完整值对外泄露，只能说明观测口径下没有发生，不能声称实际泄露率已下降。','',
        '下一项研究验证应固定当前接口与共同提示，再测试未用来修复接口的新目标/状态组合；继续重跑这12题不能证明泛化。','']
    (n.ROOT/'REPORT.md').write_text('\n'.join(lines))
    print('REPORT_WRITTEN native same-cohort 144 episodes')


if __name__=='__main__':analyze()
