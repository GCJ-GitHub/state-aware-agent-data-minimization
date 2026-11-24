"""Offline analysis of the frozen autonomous 2x2 pilot; no inference calls."""
import json
import random
from collections import Counter
import necessity_factorial as e

LABELS = {'fixed_soft': '固定建议／取数不强制', 'fixed_enforced': '固定建议／强制验证',
          'planned_soft': '规划建议／取数不强制', 'planned_enforced': '规划建议／强制验证'}


def analyze():
    e.verify()
    summary = e.io.load(e.ROOT/'summary.json')
    audit = e.io.load(e.ROOT/'audit.json')
    metrics = e.io.load(e.ROOT/'metrics.json')
    assert len(metrics) == 144 and audit['episodes'] == 144 and audit['all_passed']
    cases = {c['id']: c for c in e.io.load(e.ROOT/'tasks.json')}
    index = {(m['id'], m['arm'], m['seed']): m for m in metrics}
    assert len(index) == 144
    keys = ('task_success', 'unique_raw_fields', 'outside_justification_fields',
            'expired_evidence_fields', 'predicate_queries', 'backend_private_reads',
            'tools', 'model_calls', 'confirmations', 'any_leak')
    clusters = {}
    for cid in cases:
        by_seed = []
        for seed in e.SEEDS:
            f0, f1, p0, p1 = [index[cid, arm, seed] for arm in e.ARMS]
            by_seed.append({
                'query_advice': {k: ((p0[k]-f0[k])+(p1[k]-f1[k]))/2 for k in keys},
                'read_enforcement': {k: ((f1[k]-f0[k])+(p1[k]-p0[k]))/2 for k in keys},
                'interaction': {k: (p1[k]-p0[k])-(f1[k]-f0[k]) for k in keys}})
        clusters[cid] = {factor: {k: sum(r[factor][k] for r in by_seed)/3 for k in keys}
                         for factor in by_seed[0]}
    rng = random.Random(20261123712)
    effects = {}
    for factor in ('query_advice', 'read_enforcement', 'interaction'):
        samples = {k: [] for k in keys}
        for _ in range(5000):
            draw = [rng.choice(list(clusters.values())) for _ in clusters]
            for k in keys:
                samples[k].append(sum(c[factor][k] for c in draw)/len(draw))
        effects[factor] = {k: {'difference_per_episode': sum(c[factor][k] for c in clusters.values())/len(clusters),
                              'ci95': [sorted(samples[k])[124], sorted(samples[k])[4874]]} for k in keys}
    query_ids = {cid for cid, c in cases.items() if e.make_verifier(c).authority.probes}
    query_subset = {}
    for arm in e.ARMS:
        part = [m for m in metrics if m['arm'] == arm and m['id'] in query_ids]
        query_subset[arm] = {'n': len(part), 'predicate_queries': sum(r['predicate_queries'] for r in part),
                             'backend_private_reads': sum(r['backend_private_reads'] for r in part),
                             'query_advice_followed': sum(r['query_advice_followed'] for r in part),
                             'successful_probes': sum(r['successful_probes'] for r in part)}
    http = {a: Counter() for a in e.ARMS}
    for path in (e.ROOT/'episodes').glob('*/http.jsonl'):
        arm = path.parent.name.rsplit('__', 2)[1]
        for line in path.read_text().splitlines():
            row = json.loads(line)
            http[arm]['attempts'] += 1
            http[arm]['ok' if row['ok'] else 'errors'] += 1
    versions = Counter()
    visible_advice = {a: Counter() for a in e.ARMS}
    failure_diagnostics = []
    traces = []
    for path in sorted((e.ROOT/'episodes').glob('*/result.json')):
        row = e.io.load(path)
        versions.update(q.get('model_version') for q in row['requests'])
        m = index[row['id'], row['arm'], row['seed']]
        if not m['task_success']:
            failure_diagnostics.append({'id': row['id'], 'arm': row['arm'], 'seed': row['seed'],
                'tool_calls': len(row['events']), 'model_calls': len(row['requests']),
                'classification': 'no_tool_executed_format_failure' if not row['events'] else 'workflow_failure',
                'last_outputs': row['outputs'][-3:]})
        event_index = 0
        for turn, raw in enumerate(row['outputs']):
            call = e.parse(raw)
            if not call:
                continue
            event = row['events'][event_index]
            event_index += 1
            if call['name'] != 'probe' or event['response'].get('error'):
                continue
            cache = e.io.load(path.parent/f'{turn:02d}.json')
            text = cache['messages'][-1]['content']
            feedback = {}
            if text.startswith('<tool_response>\n'):
                feedback = json.loads(text.split('\n', 1)[1].rsplit('\n', 1)[0])
            elif 'Current feedback: ' in text:
                feedback = json.loads(text.split('Current feedback: ', 1)[1])
            hint = feedback.get('recommended_probe')
            visible_advice[row['arm']]['successful_queries'] += 1
            if hint is not None:
                visible_advice[row['arm']]['had_visible_hint'] += 1
                visible_advice[row['arm']]['matched_visible_hint'] += call['arguments'].get('name') == hint
            elif feedback.get('status') == 'ready':
                visible_advice[row['arm']]['queried_while_plan_ready_no_hint'] += 1
            elif 'tool_contracts_and_task' in feedback:
                visible_advice[row['arm']]['queried_before_initial_inspect'] += 1
            else:
                visible_advice[row['arm']]['other_query_without_nonempty_hint'] += 1
        if row['family'] == 'evidence_drift' and row['seed'] == 19:
            traces.append({'id': row['id'], 'arm': row['arm'],
                           'steps': [{'tool': ev['call']['name'], 'action': ev['call']['arguments'].get('action'),
                                      'returned_fields': ev['details'].get('returned_fields', []),
                                      'read_verdict': ev['details'].get('read_verdict'),
                                      'read_blocked': ev['details'].get('read_blocked', False),
                                      'error': ev['response'].get('error')}
                                     for ev in row['events']]})
    e.io.dump(e.ROOT/'factorial-analysis.json', {'paired_task_cluster_effects': effects,
              'query_subset_case_ids': sorted(query_ids), 'query_subset': query_subset,
              'visible_query_advice': {a: dict(c) for a, c in visible_advice.items()},
              'http_by_arm': {a: dict(c) for a, c in http.items()}, 'model_versions': dict(versions),
              'failure_diagnostics': failure_diagnostics,
              'failure_metrics': [m for m in metrics if not m['task_success']]})
    e.io.dump(e.ROOT/'drift-example-traces.json', traces)
    lines = ['# 自主 MaaS 2×2 小规模验证', '',
             '日期：2026-11-23。12 个新任务条件 × 4 组 × 3 次，共 144 条。模型为同一 MaaS `qwen3.8-flash`。', '',
             '**这是自主模型实际调用结果，和先前 0 次模型调用的离线原型检查分开。** 每个查询、取数、确认和执行调用均由模型生成；框架不补工具名、参数或执行动作。', '',
             '## 全量结果', '',
             '| 组别 | 任务成功 | 模型收到的不同原值字段次 | 不符合读取理由的字段次 | 其中证据过期字段次 | 事后未用字段次 | 判断查询 | 工具调用 | 模型调用 | 用户确认 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {t["task_success"]}/{t["n"]} | {t["unique_raw_fields"]} | {t["outside_justification_fields"]} | {t["expired_evidence_fields"]} | {t["hindsight_unused_fields"]} | {t["predicate_queries"]} | {t["tools"]} | {t["model_calls"]} | {t["confirmations"]} |')
    lines += ['', '字段按每条轨迹去重后求和；3 次重复不是 3 倍独立任务。事后未用并不自动等于不当获取。不符合理由包括过期证据和当前步骤范围问题，需结合明细判断。任务成功只表示满足业务目标、用户路线效用和必要确认；它不掩盖取数违规。', '',
              '## 整体成功率与格式失败', '',
              f'全量成功 {sum(m["task_success"] for m in metrics)}/144。失败 {len(failure_diagnostics)} 条，其中尚未执行任何工具的格式失败 {sum(d["classification"] == "no_tool_executed_format_failure" for d in failure_diagnostics)} 条，包含工具标签包裹、XML function/parameter 形式、数组和解释加调用等不在冻结兼容范围的返回。所有失败保留在主分母中。', '',
              '这轮没有运行后扩展解析器、补写调用或只重跑失败题。不能剔除这些失败后将整体成功率改称 100%。不同组失败数不同，整体原值总数也受未进入业务流程的样本影响，因此不能将其全部差额归因于安全机制。', '',
              '## 强制验证有没有实际触发', '',
              '| 组别 | 实际拦截次数 | 触发轨迹数 | 触发后成功轨迹数 | 任务与读取理由均满足 |',
              '|---|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {t["blocked_reads"]} | {t["blocked_episode"]} | {t["success_after_block"]} | {t["task_and_justification_success"]}/{t["n"]} |')
    lines += ['', '未强制组的影子校验只记入审计，不向模型泄露一次本应被拒绝的读取诊断。四组共同保留任务授权、计划校验、实际执行、依赖和确认检查。因此“取数不强制”不是完全没有后端控制。', '',
              '## 查询建议的效果和遵循情况', '',
              '两组都可使用全部相同接口和先验。查询因子只改变推荐查询；模型可以不遵循，所以主分析是建议的意向处理效果。下面按运行前结构确定有私有判断接口的任务子集，不按运行后是否真的查询筛选。', '',
              '| 组别 | 子集轨迹数 | 判断查询次数 | 后端私有原始读取字段次 | 与当时策略建议一致 / 成功查询 |',
              '|---|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = query_subset[arm]
        lines.append(f'| {LABELS[arm]} | {t["n"]} | {t["predicate_queries"]} | {t["backend_private_reads"]} | {t["query_advice_followed"]}/{t["successful_probes"]} |')
    lines += ['', '固定建议按固定服务提供方顺序、仍在已证明计划后停止；规划建议使用明确先验下的小图精确动态规划。它是常规算法参考，不是新的学习算法。诊断集刻意包含相反条件和先验，不能把这里的节省外推为真实业务平均节省。', '',
              '## 三种不同的数据接触与泄露', '',
              '| 组别 | 原值递送字段次（含重读） | 后端判断原始读取字段次 | 返回的不同版本判断结果次 | 回答泄露字段次 | 模拟外发泄露字段次 | 可见推理调用数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {LABELS[arm]} | {t["raw_disclosure_deliveries"]} | {t["backend_private_reads"]} | {t["predicate_results_released"]} | {t["prose_leak_fields"]} | {t["external_leak_fields"]} | {t["visible_reasoning_calls"]} |')
    lines += ['', '判断结果本身是信息披露；不能把模型少见原值说成系统无人读取。泄露仅按完整合成引用/完整数值匹配；明确要求准确费用的用户报告目标允许相应原值。未返回可见推理不代表隐藏推理安全，也未测试部分值和语义推断。', '',
              '## 分任务族', '',
              '| 任务族 | 组别 | 成功 | 不符合理由字段次 | 判断查询 | 工具调用 |',
              '|---|---|---:|---:|---:|---:|']
    for family in sorted({c['family'] for c in cases.values()}):
        for arm in e.ARMS:
            t = summary['tables'][family][arm]
            lines.append(f'| {family} | {LABELS[arm]} | {t["task_success"]}/{t["n"]} | {t["outside_justification_fields"]} | {t["predicate_queries"]} | {t["tools"]} |')
    lines += ['', '两条证据变化任务在第一份取数凭据已形成后，服务端改变钱包可用性或高额身份条件，四组采用相同触发。变化前没有成功的终结副作用。这是预先设计的状态新鲜度压力测试，不是模型被攻击诱导，也不是生产环境漂移率估计。', '',
              '## 预先指定的证据变化子集：不受格式失败混杂', '',
              '| 组别 | 成功 | 不同原值字段次 | 过期证据读取字段次 | 事后未用字段次 | 实际拦截 | 拦截后成功 | 工具调用 | 模型调用 | 确认 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['evidence_drift'][arm]
        lines.append(f'| {LABELS[arm]} | {t["task_success"]}/{t["n"]} | {t["unique_raw_fields"]} | {t["expired_evidence_fields"]} | {t["hindsight_unused_fields"]} | {t["blocked_reads"]} | {t["success_after_block"]} | {t["tools"]} | {t["model_calls"]} | {t["confirmations"]} |')
    lines += ['', '这是运行前就指定的两个任务，不是运行后筛出的成功样本。两种查询条件下均可直接比较取数约束；样本仍只有两种状态变化，不能据此声称跨业务普遍可靠。', '',
              '## 配对因子差异', '',
              '按 12 个任务整体重采样 5,000 次，保留各任务四组和三个种子。差值均为每轨迹平均：查询建议=规划减固定；强制验证=强制减不强制，各自对另一个因子取平均。交互是差中差。', '',
              '| 因子 | 指标 | 平均差 | 95% bootstrap 区间 |', '|---|---|---:|---|']
    for factor in ('query_advice', 'read_enforcement', 'interaction'):
        for k in ('task_success', 'outside_justification_fields', 'predicate_queries', 'tools', 'model_calls'):
            v = effects[factor][k]
            scale = 100 if k == 'task_success' else 1
            unit = ' 百分点' if scale == 100 else ''
            lines.append(f'| {factor} | {k} | {v["difference_per_episode"]*scale:.4f}{unit} | [{v["ci95"][0]*scale:.4f}, {v["ci95"][1]*scale:.4f}] |')
    lines += ['', '只有 12 个设计任务、6 个任务族，区间只条件于当前样本。全成功时零差区间不证明普遍等效。两个因素主要由不同任务族诊断，不能据交互值断言在复杂同场景中完全独立。', '',
              '## 成本、传输与审计', '',
              '| 组别 | prompt token | completion token | 截断调用 | 停顿恢复 | HTTP 尝试 | HTTP 错误 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        h = http[arm]
        lines.append(f'| {LABELS[arm]} | {t["prompt_tokens"]} | {t["completion_tokens"]} | {t["truncated_calls"]} | {t["recoveries"]} | {h["attempts"]} | {h["errors"]} |')
    lines += ['', f'正式成功模型返回 {audit["model_inputs"]} 次，逐步重放 {audit["episodes"]} 条轨迹通过。HTTP 错误统计 `{json.dumps(summary["http_errors"])}`。成功返回先存盘、再执行模拟工具；恢复不会重生成已保存步骤。开发阶段与正式阶段成本不混入主表。', '',
              '## 结论的边界', '',
              '- 可以验证本轮固定工具契约下的计划组合、按证据取数、查询建议及读取新鲜度校验的实际运行表现。',
              '- 若强制验证拦住证据过期读取，说明这类真实服务状态变化能产生模型自行按需无法仅凭旧观察消除的窗口；不说明传统版本校验是新算法。',
              '- 若查询减少，只支持当前诊断任务和已给先验；先验由设计者指定，尚未学习、估计或检验失配稳健性。',
              '- 数据仍合成，契约人工维护，规划器是小图枚举；模型得到相同规划辅助。没有无辅助模型或真实生产任务的全面比较。',
              '- 本轮没有 AirGapAgent、CaMeL、CapAgent 的直接复现比较，不能据此声称击败这些工作。',
              '- 未解决任意 API 自动理解、开放语义必要性、并发原子性、已成功副作用跨计划续接或自然语言输出隔离。', '',
              '## 复现文件', '',
              '`protocol.json`、`freeze.json`、`tasks.json`、`judge-fixtures.json` 固定规则与数据；评测器不把 judge-only 事实/值传入模型。`episodes/*/NN.json` 保存完整成功输入输出，`result.json` 保存工具与审计轨迹，`http.jsonl` 保存物理尝试。', '',
              '`metrics.json` 为逐轨迹指标；`factorial-analysis.json` 为配对分析和失败列表；`drift-example-traces.json` 为不含原值的状态变化示例。开发格式失败保存在 `development-format-v0/`，修正后开发轨迹在 `development/`。', '',
              '```bash', 'python3 necessity_factorial.py audit', 'python3 necessity_factorial.py summarize', 'python3 necessity_factorial_report.py', '```', '']
    lines += ['## 模型是否实际看到了查询建议', '',
              '| 组别 | 成功查询 | 输入中有非空建议 | 与输入中实际可见建议一致 |', '|---|---:|---:|---:|']
    for arm in e.ARMS:
        t = visible_advice[arm]
        lines.append(f'| {LABELS[arm]} | {t["successful_queries"]} | {t["had_visible_hint"]} | {t["matched_visible_hint"]} |')
    lines += ['', '这项检查直接读取每次查询的已保存模型输入；不把模型尚未看见的内部建议称为已经遵循。', '']
    lines += ['## 本轮结论', '',
              '1. 在预先指定的证据变化任务中，强制验证确实拒绝了模型自行发起的旧凭据读取，且之后由模型自己完成任务；这比“接口在脚本自检中会拒绝”多了一层实证。',
              '2. 查询建议没有表现出稳定的调用节省。推荐不等于真实执行策略：部分查询在初次 inspect 前发生，另一些发生在已有计划而没有查询建议时。应先补齐建议呈现与执行衔接，再判断查询优化方法本身，而不是把先前精确参考器的理论值当作实测收益。',
              '3. 整体成功率受统一文本工具协议的格式兼容限制。下一版本宜先验证原生工具调用或统一适配层，再冻结重测；不能事后修改本轮解析规则来追求满分。',
              '4. 所有组均未观察到完整值向回答或模拟第三方泄露；测得的主要收益是减少证据过期时的读取，不是证明降低了已发生的泄露率。', '']
    (e.ROOT/'REPORT.md').write_text('\n'.join(lines))
    print('REPORT_WRITTEN 144 autonomous episodes')


if __name__ == '__main__':
    analyze()
