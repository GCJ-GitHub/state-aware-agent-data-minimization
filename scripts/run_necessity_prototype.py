"""Run and document OFFLINE mechanics. Never calls an LLM or a real service."""
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from necessity_v2.acquire import Query, recommend
from necessity_v2.core import Denied
from necessity_v2.scenarios import appointments, delivery, refund, scripted_complete, two_private_checks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'necessity-v2-prototype'


def execute_ready(name, verifier):
    front = verifier.inspect()
    result = scripted_complete(verifier, verifier.frontier()['accepted_plans'][0])
    return {'case': name, 'before_execution': front, **result}


def main():
    OUT.mkdir(exist_ok=True)
    cases = [execute_ready('refund_wallet', refund()),
             execute_ready('refund_bank_normal', refund(wallet=False)),
             execute_ready('refund_bank_high_value', refund(wallet=False, high=True)),
             execute_ready('user_prefers_bank_over_less_data', refund(prefer_bank=True)),
             execute_ready('user_requests_exact_quotes', refund(exact_quotes=True)),
             execute_ready('two_appointments_shared_identity', appointments()),
             execute_ready('two_appointments_home', appointments(online=False))]
    v = refund(private_wallet_check=True)
    before = v.inspect()
    v.accept_evidence(v.authority.probe('check_wallet_constraints'))
    cases.append({'initial_unknown': before, **execute_ready('refund_predicate_then_execute', v)})
    for within in (True, False):
        v = delivery(within_radius=within)
        before = v.inspect()
        v.accept_evidence(v.authority.probe('check_pickup_radius'))
        cases.append({'initial_unknown': before, **execute_ready('delivery_radius_' + str(within), v)})
    v = delivery(pickup=False)
    cases.append(execute_ready('delivery_skip_unnecessary_private_probe', v))
    # Deliberate state-change fault. The old read has not executed an action.
    v = refund(wallet=False)
    sid = v.propose(v.frontier()['accepted_plans'][0].nodes)
    grant = v.issue(sid, 'bank_verify_low')
    v.authority.update_fact('wallet_available', True)
    try:
        v.read(grant['grant'], grant['fields'], v.authority.resource)
        raise AssertionError('Stale negative evidence was accepted.')
    except Denied:
        pass
    v.accept_evidence(v.authority.public_receipt('wallet_available'))
    cases.append(execute_ready('replan_after_better_route_appears', v))

    priors = {'wallet_fee_ok': 0.1, 'wallet_speed_ok': 0.9}
    queries = (Query('check_fee', 'wallet_fee_ok'), Query('check_speed', 'wallet_speed_ok'))
    query_rows = []
    for fee in (False, True):
        for speed in (False, True):
            weight = (0.1 if fee else 0.9) * (0.9 if speed else 0.1)
            for strategy in ('exact_dp_reference', 'fixed_speed_first'):
                v = two_private_checks(fee_ok=fee, speed_ok=speed)
                order = []
                while v.inspect()['status'] == 'need_evidence':
                    if strategy == 'exact_dp_reference':
                        name = recommend(v, queries, priors)['next_query']
                    else:
                        name = next(q for q in ('check_speed', 'check_fee') if q not in order)
                    if name is None:
                        raise AssertionError('No query available for a feasible toy task.')
                    order.append(name)
                    v.accept_evidence(v.authority.probe(name))
                run = execute_ready('query_order', v)
                query_rows.append({'fee_ok': fee, 'speed_ok': speed, 'world_probability': weight,
                                   'strategy': strategy, 'query_order': order,
                                   'query_count': len(order), **run})
    expected = {strategy: sum(r['world_probability'] * r['query_count'] for r in query_rows if r['strategy'] == strategy)
                for strategy in ('exact_dp_reference', 'fixed_speed_first')}
    assert abs(expected['exact_dp_reference'] - 1.1) < 1e-9
    assert abs(expected['fixed_speed_first'] - 1.9) < 1e-9
    suite = unittest.TestLoader().discover(str(ROOT / 'tests'), pattern='test_necessity_v2.py')
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (OUT / 'test-output.txt').write_text(log.getvalue())
    if not result.wasSuccessful():
        raise SystemExit('Offline controls failed; see test-output.txt')
    summary = {'kind': 'offline_prototype_mechanics_not_agent_evaluation', 'date': '2026-11-23',
               'model_calls': 0, 'real_service_actions': 0, 'scripted_examples': len(cases),
               'unit_tests': result.testsRun, 'unit_failures': len(result.failures), 'unit_errors': len(result.errors),
               'independent_plan_oracle_configurations': 64, 'query_order_truth_worlds': 4,
               'query_order_prior': priors, 'expected_query_counts_under_assumed_prior': expected,
               'not_claimed': ['LLM success improvement', 'stronger empirical attack resistance',
                               'global semantic necessity', 'optimal real-world query strategy',
                               'production security', 'published-method novelty']}
    for name, value in [('examples.json', cases), ('query-order-worlds.json', query_rows), ('summary.json', summary)]:
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 必要数据推导原型：离线检查', '',
             '**这是脚本和单元测试结果，不是 Agent / MaaS 对照实验。模型调用为 0。**', '',
             f'{len(cases)} 个脚本例子，{result.testsRun} 项单元测试通过；计划候选集与独立子集枚举器在 64 个完整状态/策略配置上一致。', '',
             '| 脚本场景 | 从工具依赖推导的执行字段 | 实际给脚本的原值字段数 | 后端判断查询读取的原始字段次 | 放出的判断结果数 |',
             '|---|---|---:|---:|---:|']
    for r in cases:
        lines.append(f'| {r["case"]} | {", ".join(r["derived_field_union"])} | {len(r["disclosed_raw_fields"])} | {r["connector_metrics"]["private_probe_raw_reads"]} | {r["connector_metrics"]["predicate_results_released"]} |')
    lines += ['', '## 查询顺序的小例子', '',
              '只有两个获准的独立查询：费用是否达标、时效是否达标。两者都达标才走少一个执行字段的钱包路线，否则走银行路线。', '',
              '在预设独立先验 P(费用达标)=0.1、P(时效达标)=0.9、每次查询代价为 1 时，标准动态规划参考解的期望查询数为 **1.1**，固定先查时效为 **1.9**。数字来自四个真值世界的加权精确计算，不是模型测得的成功率或现实节省。', '',
              '这验证的是“查询顺序本身可以成为研究变量”。动态规划与短路查询都是已有技术；原型没有证明新的在线算法优于已有方法，也没有把概率当成授权证据。', '',
              '## 检查覆盖', '',
              '- 多条合法路线；用户优先级优于省字段；只有明确要求最小化时才强制字段成本最小。',
              '- 同一套基础工具契约推导普通/高额退款的不同依赖，无每订单最终字段答案表。',
              '- 缺少可信证据时等待；不根据模型自称需要或高概率猜测放行。',
              '- 查询只放固定判断结果，但后端真实读取和判断结果披露均计数。',
              '- 共享依赖、每一步放行、越界多取、伪造事实、跨订单复用、重复使用。',
              '- 状态或字段变更后拒绝旧权限；也绑定排除更优路线的负面证据。',
              '- 用户确实要求准确费用时允许原值；不靠拒绝合法任务获得少读。', '',
              '## 尚未实现', '',
              '真实 LLM 自主规划、自然语言授权可靠编译、真实服务工具契约、跨进程事务、已成功副作用的跨计划续接、输出信息流隔离、复杂查询或部分值推断防护、可扩展的近似查询算法及独立盲测。已完成副作用后，原型拒绝新计划以避免模拟重复执行，不能当作自动恢复系统。', '',
              '详见 [研究方案](../docs/RESEARCH_V2.md)。运行：`python3 scripts/run_necessity_prototype.py`。', '']
    (OUT / 'REPORT.md').write_text('\n'.join(lines))
    files = list((ROOT / 'necessity_v2').glob('*.py')) + [Path(__file__), ROOT / 'tests/test_necessity_v2.py']
    (OUT / 'source-fingerprints.json').write_text(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
