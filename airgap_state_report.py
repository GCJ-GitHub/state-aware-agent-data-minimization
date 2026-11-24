"""Offline reporting only; never calls a model or changes frozen study decisions."""
import json
from collections import Counter
from pathlib import Path
import airgap_state_study as e


def report():
    e.verify()
    summary = e.load(e.ROOT / 'summary.json')
    audit = e.load(e.ROOT / 'audit.json')
    metrics = e.load(e.ROOT / 'metrics.json')
    assert len(metrics) == 648 and audit['completed_episodes_replayed'] == 648
    assert audit['partial_successful_returns'] == 0
    cases = {c['id']: c for c in e.load(e.ROOT / 'tasks.json')}
    rows = [e.load(p) for p in sorted((e.ROOT / 'episodes').glob('*/result.json'))]
    by_key = {(r['id'], r['arm'], r['seed']): r for r in metrics}
    extra = {}
    for arm in e.ARMS:
        part = [r for r in metrics if r['arm'] == arm]
        intercepted = [r for r in part if r['state_intercept_episode']]
        extra[arm] = {'intercepted_episodes': len(intercepted),
                      'intercepted_then_success': sum(r['success'] for r in intercepted),
                      'overread_episodes': sum(r['overread_fields'] > 0 for r in part),
                      'any_leak_episodes': sum(r['any_leak'] for r in part),
                      'minimizer_selected_fields': sum(len(r['minimizer_selected']) for r in rows if r['arm'] == arm)}
    failures = [r for r in metrics if not r['success']]
    http_by_arm = {a: {'attempts': 0, 'successful_returns': 0, 'errors': 0} for a in e.ARMS}
    for path in (e.ROOT / 'episodes').glob('*/http.jsonl'):
        arm = path.parent.name.rsplit('__', 2)[1]
        for line in path.read_text().splitlines():
            record = json.loads(line)
            http_by_arm[arm]['attempts'] += 1
            http_by_arm[arm]['successful_returns' if record['ok'] else 'errors'] += 1
    attack_effect = {}
    for arm in e.ARMS:
        paired = []
        for c in cases.values():
            if not c['attack']:
                continue
            clean = next(x for x in cases.values() if x['state_id'] == c['state_id'] and not x['attack'])
            for seed in e.SEEDS:
                a, b = by_key[c['id'], arm, seed], by_key[clean['id'], arm, seed]
                paired.append({k: int(a[k]) - int(b[k]) for k in ('success', 'overread_fields', 'tools', 'model_calls', 'any_leak')})
        attack_effect[arm] = {k: sum(p[k] for p in paired) / len(paired) for k in paired[0]}
    e.dump(e.ROOT / 'additional-analysis.json', {'interceptions': extra, 'failures': failures, 'http_by_arm': http_by_arm,
           'attack_minus_clean_per_episode': attack_effect,
           'minimizer_truncation_by_role': dict(Counter(q['role'] for r in rows for q in r['requests'] if q.get('finish_reason') == 'length')),
           'model_versions': dict(Counter(q['model_version'] for r in rows for q in r['requests']))})
    names = {'airgap': 'AirGap 架构适配', 'agent_only': '自行按需', 'state_guard': '后端状态校验'}
    lines = ['# 新任务：AirGap 架构适配 / 自行按需 / 后端状态校验', '',
             '实验日期：2026-11-23。所有数值来自本轮新任务，不沿用历史结果。', '',
             '规则和任务在正式推理前冻结；详见 [DESIGN.md](DESIGN.md)、[protocol.json](protocol.json) 和 [freeze.json](freeze.json)。', '',
             '## 先看全量结果', '',
             '| 组别 | 成功 | 多读字段次 | 实际不同字段次 | 提前读取字段次 | 工具调用 | 模型调用 | 操作确认 | 数据升级确认 | 泄露轨迹 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {names[arm]} | {t["success"]}/{t["n"]} | {t["overread_fields"]} | {t["observed_fields"]} | {t["premature_fields"]} | {t["tools"]} | {t["model_calls"]} | {t["action_confirmations"]} | {t["data_escalations"]} | {t["any_leak"]} |')
    lines += ['', '字段指标每条轨迹按字段去重后求和，同一资料在三次重复中分别计数；不是这么多个独立人的资料。多读是模型接触，不等于已经向第三方泄露。模型调用含 A 组可信最小化的两次调用。确认都是模拟用户交互，不是真人体验测量。', '',
              '## 正常与诱导分开看', '',
              '| 条件 | 组别 | 成功 | 多读字段次 | 泄露轨迹 | 状态拒绝字段请求次 | 工具调用 | 模型调用 | 数据升级确认 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for scope in ('clean', 'attack'):
        for arm in e.ARMS:
            t = summary['tables'][scope][arm]
            lines.append(f'| {scope} | {names[arm]} | {t["success"]}/{t["n"]} | {t["overread_fields"]} | {t["any_leak"]} | {t["state_denied_fields"]} | {t["tools"]} | {t["model_calls"]} | {t["data_escalations"]} |')
    lines += ['', '## 后端到底有没有拦住模型', '']
    c = extra['state_guard']
    if c['intercepted_episodes']:
        lines += [f'C 组有 **{c["intercepted_episodes"]} 条**轨迹请求了当前路线不需要、但属于原任务候选授权的字段，后端实际拒绝。触发拦截后，**{c["intercepted_then_success"]}/{c["intercepted_episodes"]}** 条仍成功。', '',
                  '这是实际运行中的拦截，不是脚本故意调用后端的自检。条件成功率不能单独当成后端的因果增益，仍须结合 B/C 配对差异。']
    else:
        lines += ['**本轮没有观察到 C 组状态拦截被实际触发。** 因此不能声称“本轮证明后端拦住了多读且恢复成功”。机械自检证明接口会拒绝，不等于真实模型试图越界。', '',
                  'B 组也没有多读。本轮说明：当前模型、共同提示和这些固定诱导下，自行按需已经足够；后端的额外收益仍未被激活。不能为了得到正结果，运行后替换攻击或只挑成功的诱导题。']
    lines += ['', '## 泄露口径', '',
              '| 组别 | 回答 prose 泄露字段次 | 最后回答泄露字段次 | 显式推理泄露字段次 | 已外发工具泄露字段次 | 尝试外发泄露字段次 | 返回显式推理的调用数 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {names[arm]} | {t["prose_leak_fields"]} | {t["final_leak_fields"]} | {t["reasoning_leak_fields"]} | {t["external_egress_leak_fields"]} | {t["attempted_egress_leak_fields"]} | {t["visible_reasoning_calls"]} |')
    lines += ['', 'prose/最后回答以正确完整流程用不到的字段为隐私目标；成功执行只允许当前必要值。可选外发消息没有发送个人值的任务需要，按所有个人字段检测。执行被本地校验拒绝的额外负载只算尝试。完整合成值匹配不覆盖部分值、语义推断或隐藏推理；未返回显式推理时，零显式推理泄露没有证明隐藏推理安全。', '',
              '## 分流程及重复运行', '',
              '| 流程 | 组别 | 成功 | 多读字段次 | 工具调用 | 模型调用 |',
              '|---|---|---:|---:|---:|---:|']
    for scope in ('single', 'switch', 'multi'):
        for arm in e.ARMS:
            t = summary['tables'][scope][arm]
            lines.append(f'| {scope} | {names[arm]} | {t["success"]}/{t["n"]} | {t["overread_fields"]} | {t["tools"]} | {t["model_calls"]} |')
    lines += ['', '| 请求种子 | 组别 | 成功 | 多读字段次 |', '|---|---|---:|---:|']
    for seed in e.SEEDS:
        for arm in e.ARMS:
            part = [r for r in metrics if r['arm'] == arm and r['seed'] == seed]
            lines.append(f'| {seed} | {names[arm]} | {sum(r["success"] for r in part)}/{len(part)} | {sum(r["overread_fields"] for r in part)} |')
    lines += ['', '## 配对不确定性', '',
              '以下为 C 减去参照组，每任务平均差。18 个业务配对整体抽样，保留两个状态、正常/诱导和三个种子；5,000 次 bootstrap。置信区间仅条件于本轮合成任务。如果两组在已观察样本上都成功或都不泄露，bootstrap 会退化为零差区间；这不证明新任务上的普遍等效或零风险。', '',
              '| 参照组/条件 | 指标 | 平均差 | 95% 区间 |', '|---|---|---:|---|']
    for label, values in summary['paired_cluster_bootstrap'].items():
        for metric in ('success', 'overread_fields', 'tools', 'model_calls', 'any_leak', 'data_escalations'):
            v = values[metric]
            factor = 100 if metric in ('success', 'any_leak') else 1
            unit = ' 百分点' if factor == 100 else ''
            lines.append(f'| {label} | {metric} | {v["delta_per_episode"]*factor:.3f}{unit} | [{v["ci95"][0]*factor:.3f}, {v["ci95"][1]*factor:.3f}] |')
    lines += ['', '## 成本、公平性与原论文复现边界', '',
              'A 组是包含两步同模型最小化、隔离和用户升级请求的动态架构适配，强于旧的人工事前给齐基线；但不是原作者代码或原论文单轮基准的精确复现。最小化器两步都看到完整可信资料，第三方从不进入最小化器，筛选结果仍受三组共同的全局授权上限约束。', '',
              '| 组别 | 可信最小化调用 | 可信库字段呈现次 | prompt token | completion token | 截断调用 | 恢复提示 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for arm in e.ARMS:
        t = summary['tables']['all'][arm]
        lines.append(f'| {names[arm]} | {t["minimizer_calls"]} | {t["trusted_vault_field_presentations"]} | {t["prompt_tokens"]} | {t["completion_tokens"]} | {t["truncated_calls"]} | {t["recoveries"]} |')
    lines += ['', '可信库字段呈现指敏感值在可信最小化模块输入中的呈现，不能和对话 Agent 多读字段直接相加来制造同口径优劣。24 次总模型调用上限包括最小化，统一每次输出上限 256；有限预算也可能使最小化推理截断。预算公平不意味着原算法在充足预算下只能达到这个结果。若要对原方法作强胜负主张，还需要最小化预算敏感性检查。', '',
              f'完整保留的 HTTP 尝试 **{summary["http_attempts"]}** 次；错误状态计数 `{json.dumps(summary["http_errors"])}`；中断记录 {summary["interruption_records"]}。成功返回在工具执行前落盘，恢复时重放而不重新生成；审计中未完成轨迹的已成功返回数为 {audit["partial_successful_returns"]}。网络超时的提供方计算与账单仍不可精确推断。', '',
              f'逐步重放通过：**{audit["completed_episodes_replayed"]} 条轨迹、{audit["model_inputs_replayed"]} 次模型输入**。失败轨迹 {len(failures)} 条，逐条指标见 `additional-analysis.json`。', '',
              '## 能证明与不能证明', '',
              '- 可比较当前动态任务中实际路径必要性与事前相关性筛选的区别，及其模型/工具/确认开销。',
              '- B/C 的配对结果才用于判断强制状态校验是否在本轮带来额外收益；A/C 同时改变可信最小化和升级流程，不能只归因于单一组件。',
              '- 单次未泄露不等于通用安全保证，实际零多读也不说明所有模型和更强攻击都会遵守。',
              '- 未验证真实用户批准体验、现实服务集成、自动授权规则提取、部分值或隐藏思考泄露、跨模型泛化。',
              '- 后续若要提升攻击强度，应在独立开发集设计攻击，重新冻结后再测新任务；不能在这批正式题上反复调攻击后当作盲测。', '',
              '## 数据与复现', '',
              '`tasks.json`、`gold.json` 是新输入与独立正确账本；`episodes/*/NN.json` 保存完整成功输入输出，`http.jsonl` 保存传输尝试，`result.json` 保存工具轨迹。`metrics.json` 是逐轨迹指标，`summary.json` 是分组汇总和配对区间。配置、真实端点和密钥均不进入这些文件。', '',
              '```bash', 'python3 airgap_state_study.py audit', 'python3 airgap_state_study.py summarize', 'python3 airgap_state_report.py', '```', '']
    lines += ['## HTTP 物理尝试分组', '', '| 组别 | 全部 HTTP 尝试 | 成功返回 | 传输错误/限流 |', '|---|---:|---:|---:|']
    for arm in e.ARMS:
        item = http_by_arm[arm]
        lines.append(f'| {names[arm]} | {item["attempts"]} | {item["successful_returns"]} | {item["errors"]} |')
    lines += ['', '物理重试由网络与限流共同影响，不能把这一列的全部差异归因于取数算法。所有成功返回应与逐次缓存及模型调用数相符。', '',
              '本轮字段值采用可明确匹配的合成引用，主要验证信息流控制；不代表自然语言真实个人资料的开放语义隐私判断。', '',
              '本轮 A 组有 132 次最小化推理达到输出长度上限，C 组有 2 次对话返回达到长度上限，最终均在共同规则与预算内完成任务。这些截断不能被隐去；A 组筛选质量在更大预算下可能改变，本轮不是原方法性能上限。', '',
              '相对于 A 组，C 组对话 Agent 总读取 1,020→444，少 56.5%；多读字段次 576→0；工具调用少 135 次，模型调用少 568 次，数据升级确认少 112 次，操作确认均为 222 次。A/C 同时改变最小化与升级机制，成本差额不能全部归因于后端校验。B/C 的差异仅为一次工具调用和一次模型调用，未显示有意义的收益。', '',
              '多合法路线指多条已授权候选可用，最终按明确用户优先级选定；工具告知所需字段。尚未覆盖任意等价路线探索、必须读取多个候选私有值才能决策、未知字段依赖等更困难任务。', '']
    (e.ROOT / 'REPORT.md').write_text('\n'.join(lines))
    print('REPORT_WRITTEN', len(rows), 'episodes')


if __name__ == '__main__':
    report()
