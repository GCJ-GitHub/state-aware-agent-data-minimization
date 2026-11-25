"""Create a readable report after the replication and trace replay finish."""
from pathlib import Path
import json

OUT = Path(__file__).resolve().parent
LABELS = {"agent_only": "Agent 自行按需", "route_table": "读前刷新路线表", "contract": "契约后端"}
FAMILY = {"route_switch": "订单送达后改走退货", "after_commit": "已取消另一单后改路",
          "no_authorized_route": "送达且没有退货授权"}


def load(file):
    return json.loads((OUT / file).read_text())


def report():
    s, audit, design = (load(n) for n in ("summary.json", "audit.json", "protocol.json"))
    tasks = load("tasks.json")
    assert s["rows"] == s["assigned"] == audit["replayed"]
    branch_counts = s["tables"]["all"]
    source_tasks = len({c["upstream_test_index"] for c in tasks})
    text = [
        "# 独立零售工具环境中的三组对照", "",
        f"以 Sierra τ-bench 零售测试集的 {source_tasks} 条人工任务作为来源，抽取 15 个不同目标订单，"
        f"每个订单构造一对状态变体，得到 30 个任务。三组各重复 3 次，共 {s['assigned']} 次，均完成离线重放。"
        "模型为 MaaS Qwen4-Max，沿用相同授权、确认、反馈和预算。", "",
        f"[冻结的上游代码与任务](https://github.com/sierra-research/tau-bench/tree/{design['upstream_commit']}/tau_bench/envs/retail)", "",
        "## 结果", "",
        "| 方案 | 正确结果 | 多读字段 | 已结束前工具调用 | 已结束后再次发起 | 确认 | 正常最终回复 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, label in LABELS.items():
        r = branch_counts[arm]
        text.append(f"| {label} | {r['correct']}/{r['n']} | {r['excess']} | {r['calls_through_outcome']} | "
                    f"{r['calls_after_close']} | {r['confirmations']} | {r['final_reply']} |")
    text += ["", "| 场景 | 方案 | 正确结果 | 多读字段 | 读取被拦后得到正确结果 |",
             "| --- | --- | ---: | ---: | ---: |"]
    for family, label in FAMILY.items():
        for arm, name in LABELS.items():
            r = s["tables"][family][arm]
            text.append(f"| {label} | {name} | {r['correct']}/{r['n']} | {r['excess']} | "
                        f"{r['recovery']}/{r['blocked_episode']} |")
    text += ["", "## 配对差", "",
             "| 后者对前者的变化 | 结果正确率差（百分点） | 每次多读字段差 | 每次业务结束前调用差 |",
             "| --- | ---: | ---: | ---: |"]
    for comparison, deltas in s["comparisons"].items():
        new, old = comparison.split("_minus_")
        cells = []
        for k, scale in (("correct",100),("excess",1),("calls_through_outcome",1)):
            r = deltas[k]
            lo, hi = (v * scale for v in r["ci95"])
            cells.append(f"{scale*r['delta']:+.3f} [{lo:+.3f}, {hi:+.3f}]")
        text.append(f"| {LABELS[old]} → {LABELS[new]} | " + " | ".join(cells) + " |")
    text += ["",
             "区间使用 5,000 次按任务对分层的 bootstrap。每个任务对保留两个状态版本和三个重复。",
             "任务完成由上游工具真实修改模拟数据库后的状态和参数校验决定。预期停止单独计分。", "",
             "## 独立性与边界", "",
             "- 上游提供合成订单、人工标注的退货参数和部分取消订单操作。读取订单、改址、退货和取消操作执行固定提交里的原工具代码。",
             "- 本研究构造初始待处理状态、统一的备用地址、条件式授权和送达时钟。用户对话采用固定请求和模拟确认。"
             "因此本轮评估是把交付机制迁移到独立工具和基准任务材料上的控制实验。"
             "任务对和中途扰动仍由本研究设计。",
             "- 工具回包只对 Agent 展示所需投影。多读以交付时当前路线为准，退货商品编号列表按一个字段计。"
             "正文原值匹配覆盖模拟地址首行、支付方式编号和商品编号，范围限于可见文字。",
             "- 时钟安排在公共状态或首笔操作提交之后的固定模型轮次。所有运行进入分母，同时报告实际发生在准备与交付之间的例数。", ""]
    for arm, name in LABELS.items():
        r=branch_counts[arm]
        text.append(f"- {name}，命中取数窗口 {r['hit_read_window']}/45 次，安全停止 {r['safe_stop']}/15，"
                    f"可见原值匹配 {r['leak']} 次，网关中断 {r['api_error']} 次。")
    text += ["", "## 复放", "", "准备固定提交的上游 checkout 后，从本仓库根目录执行：", "",
             "    python external_retail_study.py verify --upstream <upstream-checkout>",
             "    python external_retail_study.py summarize",
             "    python external-retail-study/report.py", ""]
    (OUT / "REPORT.md").write_text("\n".join(text))


if __name__=="__main__":
    report()
