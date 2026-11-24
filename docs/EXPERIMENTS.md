# 实验索引与证据等级

> 更新 2026-11-24：当前主证据、后续原型与完整轨迹见[当前进展](CURRENT_PROGRESS.md)和[当前复核指南](CURRENT_REPRODUCIBILITY.md)。下方原索引中的“最新”指 2026-11-19 的历史阶段。

## 强基线后续对照

退款强基线、物流独立目标组合、跨目标依赖以及新增签收授权规则的代码、结果和复跑入口见[四轮对照总览](STRONG_BASELINE_FOLLOWUP.md)。这些阶段由离线脚本驱动。

## 后续阶段（2026-11-23）

| 阶段 | 报告 | 代码 | 正式规模/证据 |
|---|---|---|---|
| AirGap架构适配 | [报告](../airgap-escalation-state-study/REPORT.md) | airgap_state_study.py | 648；含最小化/升级，未触发B/C强制差异 |
| 必要性原型 | [报告](../necessity-v2-prototype/REPORT.md) | necessity_v2、scripts/run_necessity_prototype.py | 0模型调用；脚本与机械检查 |
| 2×2自主模型 | [报告](../necessity-factorial-pilot/REPORT.md) | necessity_factorial.py | 144；133成功，格式失败保留 |
| 原生工具同题重测 | [报告](../necessity-native-retest/REPORT.md) | necessity_native_retest.py | 144；同题诊断，不是新留出 |
| 冻结三组新任务 | [报告](../necessity-three-arm-holdout/REPORT.md) | necessity_holdout.py | 1080；当前动态必要性主证据 |

以上阶段的完整原始目录保存在[四个压缩包](../artifacts/2026-11-23/ARCHIVE_MANIFEST.json)中；根级任务、指标、报告直接存放于对应目录。开发、格式诊断和HTTP中断保留，但不混入正式分母。

## 历史阶段（截至2026-11-19）

代码、数据和结果保留原目录关系。不同轮次的模型、自由调用程度、提示、评分和数据选择存在变化，不能把全部轮次加起来当成一个统一测试集。第一轮不是Qwen3-1.7B；后续以各轮报告为准。

| 阶段 | 代码 | 结果目录 | 报告 | 证据边界 |
|---|---|---|---|---|
| 第一轮 | run.py | `results-model` | [说明](../docs/history/FIRST-ROUND-README.md) | 探索性；Qwen2.5-0.5B，字段打分/框架执行，不是全自由Agent |
| 物流2–5轮 | round2.py 至 round5.py | `results-round2 至 results-round5` | [说明](../ROUND2.md) | 开发/同题修复；自主调用、反馈和调用格式兼容 |
| 物流6–9轮 | round6.py 至 round9.py | `results-round6 至 results-round9` | [说明](../ROUND9.md) | 新订单后逐步修复；后续轮不可视为独立新留出 |
| 物流10轮 | round10.py | `results-round10` | [说明](../ROUND10.md) | 冻结方案的新订单验证 |
| 物流11轮 | round11.py | `results-round11` | [说明](../ROUND11.md) | 模型提取规则，与人工规则比较；小样本 |
| AirGap式物流 | airgap_comparison.py | `results-airgap-comparison` | [说明](../AIRGAP-COMPARISON.md) | 方法式直接对照，不是原版完整复现 |
| 物流放行时机 | release_timing.py | `results-release-timing` | [说明](../RELEASE-TIMING.md) | 共用规则，仅放行策略的受控对照 |
| 退款放行时机 | refund_release_timing.py | `results-refund-release-timing` | [说明](../REFUND-RELEASE-TIMING.md) | 跨业务场景 |
| 退款恢复/留出 | refund_recovery.py | `results-refund-recovery-holdout` | [说明](../REFUND-RECOVERY-HOLDOUT.md) | 开发修复与后续留出分开 |
| AirGapAgent-R | airgap_r_eval.py | `results-airgap-r` | [说明](../AIRGAP-R-EVAL.md) | 56原题+28派生题；原数据、派生状态分别报告 |
| 推理与诱导 | airgap_r_thinking.py | `results-airgap-r-thinking-pressure` | [说明](../AIRGAP-R-THINKING-PRESSURE.md) | 可见思考与输出；非完整榜单 |
| 受限重答留出 | airgap_r_thinking.py | `results-airgap-r-restricted-holdout` | [说明](../AIRGAP-R-RESTRICTED-HOLDOUT.md) | 冻结重答规则后的28新题 |
| 四MaaS模型 | maas_privacy_eval.py | `results-maas-four-models` | [说明](../MAAS-FOUR-MODELS.md) | 224轨迹；服务思考预算不同 |
| 初次完整三组 | blind_three_arm.py | `blind-three-arm` | [说明](../blind-three-arm/REPORT.md) | 1080轨迹；存在SYSTEM/工具位置混杂 |
| 统一工具回包失败复测 | tool_channel_failure_retest.py | `tool-channel-failure-retest` | [说明](../tool-channel-failure-retest/REPORT.md) | 18失败任务×3组×3次=162；诊断子集 |
| 最新完整跨模型 | state_holdout_cross_model.py | `state-holdout-cross-model` | [说明](../state-holdout-cross-model/REPORT.md) | 120新任务×3组×3次×2模型=2160；当前主证据 |

## 全部原始报告入口

- [AIRGAP-COMPARISON.md](../AIRGAP-COMPARISON.md)
- [AIRGAP-R-EVAL.md](../AIRGAP-R-EVAL.md)
- [AIRGAP-R-PARTIAL-RESPONSE.md](../AIRGAP-R-PARTIAL-RESPONSE.md)
- [AIRGAP-R-REFUSAL-HOLDOUT.md](../AIRGAP-R-REFUSAL-HOLDOUT.md)
- [AIRGAP-R-REFUSAL-RETRY.md](../AIRGAP-R-REFUSAL-RETRY.md)
- [AIRGAP-R-RESTRICTED-HOLDOUT.md](../AIRGAP-R-RESTRICTED-HOLDOUT.md)
- [AIRGAP-R-RESTRICTED-RETRY.md](../AIRGAP-R-RESTRICTED-RETRY.md)
- [AIRGAP-R-THINKING-PRESSURE.md](../AIRGAP-R-THINKING-PRESSURE.md)
- [AIRGAP-R-THINKING.md](../AIRGAP-R-THINKING.md)
- [MAAS-FOUR-MODELS.md](../MAAS-FOUR-MODELS.md)
- [REFUND-RECOVERY-HOLDOUT.md](../REFUND-RECOVERY-HOLDOUT.md)
- [REFUND-RECOVERY.md](../REFUND-RECOVERY.md)
- [REFUND-RELEASE-TIMING.md](../REFUND-RELEASE-TIMING.md)
- [RELEASE-TIMING.md](../RELEASE-TIMING.md)
- [ROUND10.md](../ROUND10.md)
- [ROUND11.md](../ROUND11.md)
- [ROUND2.md](../ROUND2.md)
- [ROUND3.md](../ROUND3.md)
- [ROUND4.md](../ROUND4.md)
- [ROUND5.md](../ROUND5.md)
- [ROUND6.md](../ROUND6.md)
- [ROUND7.md](../ROUND7.md)
- [ROUND8.md](../ROUND8.md)
- [ROUND9.md](../ROUND9.md)

## 保存了哪些文件

| 目录 | 文件数 | 大小MiB |
|---|---:|---:|
| `blind-three-arm` | 22 | 7.88 |
| `data` | 2 | 7.52 |
| `results-airgap-comparison` | 2 | 0.13 |
| `results-airgap-parser-diagnostic` | 2 | 0.13 |
| `results-airgap-r` | 3 | 0.10 |
| `results-airgap-r-authorization-diagnostic` | 2 | 0.08 |
| `results-airgap-r-format-diagnostic` | 2 | 0.05 |
| `results-airgap-r-partial-response` | 2 | 0.12 |
| `results-airgap-r-refusal-holdout` | 2 | 0.15 |
| `results-airgap-r-refusal-retry` | 2 | 0.14 |
| `results-airgap-r-restricted-holdout` | 2 | 0.15 |
| `results-airgap-r-restricted-retry` | 2 | 0.15 |
| `results-airgap-r-thinking` | 2 | 0.10 |
| `results-airgap-r-thinking-pressure` | 2 | 0.13 |
| `results-maas-four-models` | 5 | 0.58 |
| `results-model` | 2 | 0.03 |
| `results-model-initial` | 2 | 0.05 |
| `results-refund-recovery` | 2 | 0.11 |
| `results-refund-recovery-holdout` | 2 | 0.11 |
| `results-refund-release-timing` | 2 | 0.12 |
| `results-release-timing` | 2 | 0.13 |
| `results-release-timing-prompt-diagnostic` | 1 | 0.07 |
| `results-round10` | 2 | 0.11 |
| `results-round11` | 2 | 0.11 |
| `results-round2` | 2 | 0.14 |
| `results-round3` | 2 | 0.10 |
| `results-round4` | 2 | 0.05 |
| `results-round5` | 2 | 0.05 |
| `results-round6` | 2 | 0.09 |
| `results-round7` | 2 | 0.04 |
| `results-round8` | 2 | 0.05 |
| `results-round9` | 2 | 0.06 |
| `results-scripted` | 2 | 0.03 |
| `state-holdout-cross-model` | 26 | 29.94 |
| `tool-channel-failure-retest` | 13 | 2.24 |

`*-diagnostic`和preflight材料是调试/接入诊断，不能并入正式成绩。MaaS的HTTP限流与中断缺轨迹见最新报告和transport-sensitivity.json。

上游公开数据及派生题保留来源索引，引用和许可见THIRD_PARTY_NOTICES.md。
