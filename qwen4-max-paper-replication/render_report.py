"""Write a model-replication result report from recorded, rescored traces."""
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
import qwen4_paper_replication as replication

LABELS = {
    "strong": ("强基线自主对照", "correct", "excess_fields", "tool_calls", "leak_episode"),
    "three-arm": ("事前给齐、自行按需、后端校验", "task_success", "hindsight_unused_fields", "tools", "any_leak"),
    "airgap": ("AirGap 式对照", "success", "overread_fields", "tools", "any_leak"),
    "native-factorial": ("原生工具接口消融", "task_success", "outside_justification_fields", "tools", "any_leak"),
    "text-factorial": ("文本工具接口消融", "task_success", "outside_justification_fields", "tools", "any_leak"),
}


def main():
    summary = replication.strong.read_json(OUT / "summary.json")
    paired = replication.strong.read_json(OUT / "paired-analysis.json")
    assigned = sum(row["assigned"] for row in summary.values())
    done = sum(row["recorded"] for row in summary.values())
    content = [
        "# Qwen4-Max 复现实验结果",
        "",
        f"已保存 {done}/{assigned} 个正式运行。所有实验共用 Qwen4-Max 网关别名。",
        "",
        "| 实验 | 已保存／分派 | 可评分 | 网关中断 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, result in summary.items():
        table = result["arms"].values()
        content.append(f"| {LABELS[name][0]} | {result['recorded']}/{result['assigned']} | "
                       f"{sum(r['scored'] for r in table)} | {sum(r['gateway_interruptions'] for r in table)} |")
    content += ["", "以下分组结果仅在相应实验已保存全部预定运行时列出。", ""]
    for name, result in summary.items():
        if result["recorded"] != result["assigned"]:
            continue
        label, correct, overread, tools, leaks = LABELS[name]
        content.extend([
            f"## {label}", "",
            "| 方案 | 分派 | 可评分 | 正确业务结果 | 多读 | 可见泄露运行 | 工具调用 | 模型响应 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for arm, metrics in result["arms"].items():
            content.append(
                f"| {arm} | {metrics['recorded']} | {metrics['scored']} | {metrics.get(correct, 0)} | "
                f"{metrics.get(overread, 0)} | {metrics.get(leaks, 0)} | {metrics.get(tools, 0)} | "
                f"{metrics.get('model_calls', 0)} |")
        content.append("")
        if name == "strong":
            for arm, metrics in result["arms"].items():
                after = metrics.get("calls_after_close", 0)
                through = metrics.get("tool_calls", 0) - after
                content.append(f"- {arm} 正常回复 {metrics.get('final_reply', 0)} 次，"
                               f"业务关闭前后工具调用分别为 {through:,} 和 {after:,}，"
                               f"被拒后正确恢复 {metrics.get('recovered', 0)} / "
                               f"{metrics.get('blocked_read_episode', 0)}。")
            content.append("")
        content.extend([
            "| 配对比较（前者减后者） | 匹配次数 | 平均正确率差（百分点） | 平均多读差 | 平均工具调用差 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        contrast_sets = (("后端", paired[name]["qwen4_arm_contrasts"]),
                         ("Qwen4-Max 减 Qwen3.8-Flash", paired[name]["cross_model_by_arm"]))
        for title, contrasts in contrast_sets:
            for group, metrics in contrasts.items():
                if not metrics.get("matched"):
                    continue
                delta = metrics["mean_delta"]
                ci = metrics["paired_ci95"]
                ranges = [(correct, 100), (overread, 1), (tools, 1)]
                cells = [f"{delta[k]*scale:+.3f} [{ci[k][0]*scale:+.3f}, {ci[k][1]*scale:+.3f}]"
                         for k, scale in ranges]
                content.append(f"| {title} {group} | {metrics['matched']} | " + " | ".join(cells) + " |")
        content.append("")
    content.extend([
        "95% 区间对任务对或任务 ID 做成簇重采样。多读指标沿用各实验原来的定义。"
        "三组自主对照使用最终执行未用的字段数，强基线使用交付时多余的字段数。"
        "应在同一实验内比较模型和方法。", "",
    ])
    (OUT / "REPORT.md").write_text("\n".join(content))


if __name__ == "__main__":
    main()
