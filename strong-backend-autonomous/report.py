"""Render comparison report from the formal episode records."""

from collections import Counter, defaultdict
import json
from pathlib import Path

STUDY = Path(__file__).resolve().parent
T, C = "route_table", "contract"
ARMS = (T, C)
LABELS = {T: "读前刷新路线表", C: "版本化契约后端"}
FAMILY = {"preferred_returns": "首选退款路线恢复", "after_commit": "自提点已改后的改路",
          "no_authorized_route": "钱包关闭且银行未授权"}


def load(name):
    return json.loads((STUDY / name).read_text())


def fraction(numerator, denominator):
    return f"{numerator}/{denominator}" if denominator else "无适用样本"


def recovery(row):
    return fraction(row["recovered"], row["blocked_read_episode"])


def interval(summary, name, scale=1):
    lo, hi = summary["contract_minus_table_paired_ci95"][name]
    return f"[{lo * scale:+.3f}, {hi * scale:+.3f}]"


def write():
    summary = load("summary.json")
    audit = load("audit.json")
    freeze = load("freeze.json")
    rows = load("metrics.json")
    tasks = {r["id"]: r for r in load("tasks.json")}
    assert summary["recorded"] == audit["replayed_and_independently_counted"] == len(rows) == 720
    a, b = (summary["tables"]["all"][arm] for arm in ARMS)
    assert a["n"] == b["n"] == 360
    content = [
        "# 两种运行时后端的自主 Agent 对照",
        "",
        "60 对新合成任务，120 个任务成员。两组对每个成员各运行 3 次，共 720 次。"
        "两组共用 MaaS qwen3.8-flash 网关别名、工具接口、授权、确认、执行与恢复规则。"
        "路线表在读前刷新状态并按组合规则重新校验。契约后端还验证准备阶段绑定的证据与值版本。",
        "",
        "| 指标 | 读前刷新路线表 | 版本化契约后端 | 契约减路线表 |",
        "|---|---:|---:|---:|",
    ]
    for metric, label in (
        ("excess_fields", "过度交付字段实例"), ("raw_fields", "全部交付字段实例"),
        ("correct", "正确业务结果（含预期安全停止）"), ("completed", "完成本可执行的业务"),
        ("safe_stop", "正确停止"), ("blocked_read_episode", "至少拒绝一次字段读取的运行"),
        ("blocked_reads", "被拒字段读取次数"), ("stale_grant_denials", "授权或相关证据失效拒绝"),
        ("route_denials", "当前路线已不合法的拒绝"), ("recovered", "被拒读取后得到正确结果的运行"),
        ("identity_verifications", "身份核验次数"), ("duplicate_verifications", "同版本重复身份核验"),
        ("duplicate_effects", "重复提交效果"), ("model_calls", "模型响应次数"), ("tool_calls", "有效工具调用次数"),
        ("confirmations", "批准次数"), ("leak_episode", "模型可见文字中出现原值的运行"),
        ("final_reply", "生成最终回复的运行"), ("transport_interruption", "终止于 API 故障"),
    ):
        content.append(f"| {label} | {a[metric]} | {b[metric]} | {b[metric]-a[metric]:+d} |")
    content += [
        "",
        f"路线表和契约后端的可执行任务分别完成 **{fraction(a['completed'], 360-a['expected_stop'])}** 和 "
        f"**{fraction(b['completed'], 360-b['expected_stop'])}**。"
        f"预期停止分别为 **{fraction(a['safe_stop'], a['expected_stop'])}** 和 "
        f"**{fraction(b['safe_stop'], b['expected_stop'])}**。"
        f"至少一次读被拒后的正确结果分别为 **{recovery(a)}** 和 **{recovery(b)}**。"
        "各组被拒的任务数量不同，恢复比例需要结合两组都被拒的配对分析一起看。",
        "",
        "## 配对差与区间",
        "",
        "95% 区间按任务对分层重采样 5,000 次，每次保留一对的两个成员及全部重复。",
        "",
        "| 指标（契约减路线表） | 每次运行的平均差 | 95% 区间 |",
        "|---|---:|---:|",
    ]
    for metric, label, scale in (
        ("excess_fields", "多交付字段", 1), ("correct", "正确业务结果率（百分点）", 100),
        ("model_calls", "模型响应", 1), ("tool_calls", "工具调用", 1), ("confirmations", "批准", 1),
    ):
        content.append(f"| {label} | {(b[metric]-a[metric])*scale/360:+.3f} | {interval(summary,metric,scale)} |")
    content += [
        "",
        "## 按场景拆分",
        "",
        "| 场景 | 后端 | 正确结果 / 总数 | 多读 | 被拒后正确完成或停止 | 模型响应 | 工具调用 | 批准 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, label in FAMILY.items():
        for arm in ARMS:
            row = summary["tables"][family][arm]
            content.append(f"| {label} | {LABELS[arm]} | {row['correct']}/{row['n']} | {row['excess_fields']} | "
                           f"{recovery(row)} | {row['model_calls']} | {row['tool_calls']} | {row['confirmations']} |")

    paired = defaultdict(dict)
    for row in rows:
        paired[(row["id"], row["seed"])][row["arm"]] = row
    assert len(paired) == 360 and all(set(p) == set(ARMS) for p in paired.values())
    discordance = Counter((p[T]["correct"], p[C]["correct"]) for p in paired.values())
    both_blocked = [p for p in paired.values() if all(p[arm]["blocked_read_episode"] for arm in ARMS)]
    count_rec = [sum(p[arm]["recovered"] for p in both_blocked) for arm in ARMS]
    version_only = [p for (case_id, _), p in paired.items()
                    if tasks[case_id]["variant"] == "control" and tasks[case_id]["fact_updates"]]
    assert len(version_only) == 90
    drift_read = [sum(p[arm]["changed_within_read_window"] for p in version_only) for arm in ARMS]
    stale_denials = [sum(p[arm]["stale_grant_denials"] for p in version_only) for arm in ARMS]
    version_correct = [sum(p[arm]["correct"] for p in version_only) for arm in ARMS]
    version_calls = [sum(p[arm]["tool_calls"] for p in version_only) for arm in ARMS]
    content += [
        "",
        f"- 同一任务同一种子只有路线表正确的 **{discordance[(1, 0)]}** 次，"
        f"只有契约后端正确的 **{discordance[(0, 1)]}** 次。",
        f"- 两边都遇到读拒绝的 **{len(both_blocked)}** 个匹配运行里，"
        f"路线表和契约后端分别有 **{count_rec[0]}**、**{count_rec[1]}** 个正确业务结果。",
        f"- 两组命中预定时钟的运行分别为 **{a['clock_applied']}/360** 和 **{b['clock_applied']}/360**。"
        f"有变化且记录到准备与读尝试之间实际发生变化的运行分别为 **{a['changed_within_read_window']}** 和 "
        f"**{b['changed_within_read_window']}**。总表保留所有指定运行。",
        f"- 在 **90 个只更新版本、路线条件真假不变**的匹配运行中，路线表和契约后端分别有 "
        f"**{drift_read[0]}** 和 **{drift_read[1]}** 次在准备和读取之间经历更新，"
        f"产生 **{stale_denials[0]}** 和 **{stale_denials[1]}** 次授权或证据失效拒绝，"
        f"正确结果 **{version_correct[0]}/90** 和 **{version_correct[1]}/90**，"
        f"工具调用 **{version_calls[0]}** 和 **{version_calls[1]}**。",
        "",
        "## 复核与边界",
        "",
        "- 数据由三个合成工作流家族做结构化配对。任务标识、权限、值和事件变体采用冻结夹具。"
        "评价覆盖顺序模拟器内的数据交付和模型可见输出。",
        "- 独立计分从工具回包和业务事件重建字段交付、必要性和正确结果。"
        "重放全部 720 条记录并校对工具回包及状态轨迹。"
        "文字泄露口径是模型可见文字对合成原值的匹配。执行接口中必需的字段按业务用值统计。",
        f"- 启动时网关限流。保留 **{freeze['transport_amendment']['partial_trial_records']}** 条不计分传输试跑记录。"
        "调整全局请求速率和重试后，从头执行整个矩阵。任务、模型请求、提示、策略和评分保持冻结。",
        f"- 正式调用的 HTTP 请求次数为 **{a['http_attempts']}** 和 **{b['http_attempts']}**，含传输重试。"
        "模型响应与工具调用开销分开统计。网关仅返回模型别名，服务端精确权重快照无法独立核实。",
        "",
    ]
    invalid = [
        (r, load(f"episodes/{r['id']}__{r['arm']}__{r['seed']}.json"))
        for r in rows if not r["correct"]
    ]
    if invalid:
        content.extend(["## 未得到正确业务结果的运行", ""])
        for row, trace in invalid:
            content.append(
                f"- {row['id']}，{LABELS[row['arm']]}，种子 {row['seed']}。"
                f"预期提交 {tasks[row['id']]['expected_commits']}，实际提交 {trace['commits']}。"
                f"结束原因 {trace['end']}。模型或网关记录 {trace['protocol_errors']}。"
            )
        content.append("")
    content.extend([
        "## 结果解读",
        "",
        "两种后端在这批任务中都实现了零过度交付。路线表刷新已经能保护当前路线所需字段。"
        "契约后端额外执行证据版本约束，在条件真假未变的对照中引入了重新准备。"
        "全量工具调用的配对区间跨零，版本更新子集可以解释具体的恢复成本。"
        "结果支持在交付时强制检查字段必要性，未观察到更严格的版本绑定进一步减少原值暴露。",
        "",
    ])
    (STUDY / "REPORT.md").write_text("\n".join(content))


if __name__ == "__main__":
    write()
