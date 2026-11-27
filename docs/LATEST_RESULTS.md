# 当前论文结论与证据

更新：2026-11-27。最新稿件见[论文 PDF](../paper/paper.pdf)和[论文目录](../paper/README.md)。

**任务办对了，数据却多给了。** 在引言引用的 τ-bench 零售回放里，订单在地址读请求准备后、原值返回前变为已送达。Agent 最终按要求完成退货，模型却收到六个当前流程用不上的地址字段。论文研究这段时间里取数理由如何失效，以及平台如何在交付前挡住原值，并让 Agent 自行恢复。这里的多读指字段已交付给模型。该轮对最终可见文本的原值匹配三组均为零。见[轨迹与复放](../external-retail-study/README.md#引言中的回放轨迹)。

| 实验 | 主要结果 | 原始材料 |
| --- | --- | --- |
| 三组原生工具主对照，两个 MaaS 模型 | 自行按需组在两个模型下都放行了 144 个基于旧状态的字段，后端都降到 0。Qwen4-Max 下三组均完成 360/360，后端比自行按需多 5 次工具调用，120 次拦截后全部恢复。 | [Qwen3.8-Flash](../necessity-three-arm-holdout/REPORT.md) · [Qwen4-Max](../qwen4-max-paper-replication/REPORT.md) |
| 可组合路线表与契约后端 | 两组在 Qwen4-Max 下均为 360/360、零多读。仅证据版本变化的 90 次运行里，契约后端多 90 次旧授权拒绝，增加 360 次业务结束前的调用。 | [原强基线](../strong-backend-autonomous/REPORT.md) · [跨模型结果](../qwen4-max-paper-replication/REPORT.md) |
| AirGap 式事前筛选加确认 | Qwen4-Max 下三组均为 216/216。事前筛选组多读 366 个字段、发起 182 次补取审批。两种按需组在该环境均为零多读。 | [协议与原结果](../airgap-escalation-state-study/REPORT.md) · [Qwen4-Max](../qwen4-max-paper-replication/REPORT.md) |
| 文本工具与原生工具消融 | Qwen4-Max 两个接口下各臂均为 36/36。固定或规划查询顺序时，强制读校验都把因旧证据放行的字段从 12 降到 0。 | [完整复现](../qwen4-max-paper-replication/REPORT.md) |
| τ-bench 零售工具迁移 | 三组均为 90/90。两种后端将自行按需组的 270 次过时字段交付降到 0，各节省 45 次业务结束前的调用。 | [零售对照与复放入口](../external-retail-study/REPORT.md) |
| 规则维护与审计 | 两个后端各需 3 条新业务声明。各通过 36 个验证用例和 12 个旧流程回归，检出 15/15 注入误配，共用结构化日志后均能重建 8/8 审计判定。 | [维护与审计](../maintenance-audit-study/REPORT.md) |
| 业务结束回包诊断 | 12 次配对运行都正确且零多读。明确结束回包让正常回复从 4/12 升到 12/12，业务关闭后的工具调用从 225 降到 8。 | [诊断报告](../qwen4-terminal-diagnostic/REPORT.md) |

Qwen4-Max 五项正式复现共 2,736 次，均通过离线轨迹重放。强基线组 45 次网关中断均发生在正确业务结果之后，正常最终回复另计。离线重跑七项脚本，逐项与原档案一致。见[轨迹审计](../qwen4-max-paper-replication/trace-audit.json)和[离线复跑](../qwen4-max-paper-replication/offline-audit.json)。

## Gaia2、窄绑定与组合规则维护

- [公开任务全量结果](../independent-holdout/gaia2/scale/README.md)覆盖 160 道题、480 次运行。补齐网关中断后，173 次业务通过，347 次触发至少一个原生事件。这部分为自行按需的可达性评估。
- [受控窗口](../independent-holdout/gaia2/delivery-window/README.md)显示，读准备时仍有效的原值可以在取消后进入模型；[交付前都刷新](../independent-holdout/gaia2/delivery-refresh/README.md)后两组均拦住了观察到的旧值。
- [五道追加题的异步三组对照](../independent-holdout/gaia2/async-delivery-holdout/REPORT.md)共 45 次。五个匹配三元组的旧值交付为 2、0、0，三组均保留三个仍在路线范围内的商品 ID。全量读准备组的三次旧值交付都发生在失败运行，四次成功都未命中窗口。论文以此补充交付时机的证据。
- [窄绑定同期对照](../refund-state-return-study/selective-contract/README.md)中，只绑定银行授权撤回代数和必要字段版本消除了原契约的 3 次误拒绝和 12 次恢复调用。新契约与强路线表均零误放行、15/15 成功。
- [组合退款维护](../refund-composition-maintenance-study/README.md)中，每组 256/256 正确、零误放行。人工都加了 3 条规则，回归各 32/32，结构化审计各能解释 7/7。路线表额外生成一层路线配方。未测人工维护或排障用时。

## 结论与下一步

- **实证支持的主张**：业务状态变化后，平台在交付前重新检查字段必要性，可以减少过时取数，并让 Agent 在例外发生后继续完成任务。
- **强基线划出的边界**：交付前刷新状态的可组合路线表也能实现这一点。窄绑定契约与同等校验的路线表在本轮退款对照中逐对一致；组合规则的差异落在派生路线表示。
- **外部验证及边界**：τ-bench 补充对照用了独立编写的订单、测试标注和执行工具，状态扰动与条件授权由本研究设计。进一步验证可使用由独立人员提供的状态变化和任务协议。
- **指标范围**：字段交付、可见原值披露、业务提交和对话正常结束分别计分。报告按实验保留各自多读定义与配对区间。

[全部实验索引](EXPERIMENTS.md) · [复核与重跑入口](CURRENT_REPRODUCIBILITY.md) · [完整原始轨迹归档清单](../artifacts/2026-11-23/ARCHIVE_MANIFEST.json)
