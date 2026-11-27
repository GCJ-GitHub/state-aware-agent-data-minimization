# 状态感知 Agent 数据最小化：方法、代码与实验

更新：**2026-11-27**。

## 论文主线

**业务状态变化会让取数理由失效。** 例如，Agent 选好银行退款后，钱包在账户字段交付前恢复，按照用户原来的偏好，银行字段已用不上。连接器在原值进入模型前重验当前路线、步骤和字段必要性。拒绝时提供恢复提示，Agent 再自行查状态、调整路线、复用仍有效的核验和已完成事项，或者在没有授权路线时正确停止。

## 三项贡献

1. **定义交付时的字段必要性。** 把授权、路线偏好、当前状态和步骤前置条件统一到连接器的读取判定。
2. **实现两种后端与同一条恢复路径。** 可组合路线表和契约后端都能在原值交付前刷新并校验。窄绑定契约保留授权撤回代数和所需字段版本，当前路线仍在交付前检查。两种后端均由 Agent 自行恢复。
3. **测量减曝效果和恢复代价。** 两个模型及 τ-bench 零售工具环境复现了交付校验的效果。在直接对照中，两种后端都做到零多读。Qwen4-Max 强基线中，仅证据版本变化而路线仍合法时，版本绑定额外触发 90 次读拒绝，增加 360 次业务结束前的工具调用。

## 讨论与结论

- **跨模型复现。** 在退款和物流任务中，Qwen3.8-Flash 与 Qwen4-Max 的自行按需组各交付 144 个过时字段，交付前校验都降到 0。两种模型分别有 119/120 和 120/120 次读被拦后的业务恢复。
- **跨工具环境复现。** τ-bench 零售对照在 Qwen4-Max 上运行。两种后端都把多读从 270 降到 0，三组均为 90/90。上游提供订单、测试标注和业务工具，状态切换和条件授权由本研究设计。
- **后端取舍。** 两种后端都可在交付前重算必要性。旧契约绑定整个计划的支持证据，某些仍合法的读取也会被拒；窄绑定版本在受控退款中消除了这项额外恢复。
- **独立出题待验证。** 等外部作者提交任务对、状态变化和预期答案后，用冻结的三组协议检验是否仍能少读、正确完成或安全停止，并记录恢复成本。

## 新增实证（2026-11-27）

| 实验 | 结果 | 数据、代码及复跑 |
| --- | --- | --- |
| Gaia2 全量能力覆盖 | 160 道原题各跑 3 次；Qwen4-Max 自行按需组补齐 5 次网关中断后 173/480 成功，347/480 触发原生事件 | [全量覆盖](independent-holdout/gaia2/scale/README.md) · [上游数据与版本](independent-holdout/gaia2/DATA.md) |
| 交付窗口压力测试 | 27 次；7 个匹配三元组里，自行按需和读前刷新路线表各重复交付 7 个过期值，契约交付前拦截后为 0，三组均完成 7/7 | [交付窗口](independent-holdout/gaia2/delivery-window/README.md) |
| 交付前刷新强路线表 | 18 次；两边命中窗口后均无旧值交付；8 个匹配对切换后调用为 59 和 58 次，业务成功为 8/8 和 6/8 | [同期强基线](independent-holdout/gaia2/delivery-refresh/README.md) |
| 退款多次切换与窄绑定 | 45 次同期对照；新契约减少原契约的 3 次误拒绝和 12 次额外调用，三组均 15/15 成功且零误放行，新契约与强路线表逐对一致 | [退款状态变化](refund-state-return-study/README.md) · [三组复测](refund-state-return-study/selective-contract/README.md) |
| 新增组合规则的维护和审计 | 两组各 256/256 正确且零误放行，人工各加 3 条规则、旧流程各 32/32、审计各 7/7；路线表生成 12 条配方，新契约不生成配方 | [合成退款规则、结果和判定日志](refund-composition-maintenance-study/README.md) |

全量 Gaia2 衡量原生任务和事件可达性。交付窗口是受控压力测试，测量的是挂起回包的实际发送。维护对照使用共享的规则编译和日志，人工用时与自然误配率尚未测量。

## 论文与此前实证

- **[新版论文 PDF](paper/paper.pdf)** · [LaTeX 源码与图表](paper/README.md)
- **[实验结果、论文结论与下一步](docs/LATEST_RESULTS.md)**
- **[独立 τ-bench 零售工具对照（270 次）](external-retail-study/REPORT.md)**
- [Qwen4-Max 的 2,736 次正式复现](qwen4-max-paper-replication/REPORT.md) · [配对分析](qwen4-max-paper-replication/paired-analysis.json)
- [两种强后端的自主对照](strong-backend-autonomous/REPORT.md) · [维护与审计](maintenance-audit-study/REPORT.md) · [结束回包诊断](qwen4-terminal-diagnostic/REPORT.md)

## 从这里开始

- **[论文初稿、LaTeX 源码与实验图表](paper/README.md)**

- **[当前实验、代码、效果与进展总览](docs/CURRENT_PROGRESS.md)**
- **[研究构想与方法设计背景](docs/PAPER_IDEA.md)**
- [当前材料复现与离线复核](docs/CURRENT_REPRODUCIBILITY.md)
- [全部实验索引及证据等级](docs/EXPERIMENTS.md)

![方法框架](docs/assets/paper-framework/framework.svg)

[四轮强基线对照、论文结论与投稿前验证](docs/STRONG_BASELINE_FOLLOWUP.md)

## Qwen3.8-Flash 主对照基线

新120个合成任务、60个状态配对，MaaS qwen3.8-flash，三组各重复三次，共1080次尝试。规则、授权、确认、恢复、原生工具和预算跑前冻结。

| 方案 | 业务完成 | 最终未用字段累计 | 工具调用 | 模型调用 | 确认 | 可见文字泄露轨迹 |
|---|---:|---:|---:|---:|---:|---:|
| 事前给齐 | 359/360 | 1049 | 2775 | 3134 | 139 | 1 |
| 自行按需 | 359/360 | 144 | 3487 | 3840 | 141 | 0 |
| 后端按状态校验 | 359/360 | 0 | 3446 | 3806 | 141 | 1 |

**可说：**动态任务上的不必要取数减少，业务完成率保持较高。自行按需过期字段144，后端0；120次实际拦截中119条完成。**不能说：**零最终回答泄露、稳定节省调用、全面优于完整AirGapAgent或对所有模型无损。

字段按每次尝试内去重后相加，不是真实用户数。业务完成不等于正常最终文字收尾，后者分别354/360、352/360、355/360。事前组动态事件只触发108/120，另两组120/120；三组动态子集不能作完全相同外部状态暴露的归因。详见[完整报告](necessity-three-arm-holdout/REPORT.md)和[当前总览](docs/CURRENT_PROGRESS.md)。

## 代码与原始材料

- [核心必要性/证据/交付机制](necessity_v2/core.py)
- [当前新任务运行器与主计分](necessity_holdout.py)
- [原生工具协议适配](necessity_native_retest.py)
- [任务](necessity-three-arm-holdout/tasks.json)、[逐任务评分](necessity-three-arm-holdout/metrics.json)、[配对分析](necessity-three-arm-holdout/analysis.json)
- [报告与协议](necessity-three-arm-holdout/REPORT.md)、[冻结指纹](necessity-three-arm-holdout/freeze.json)、[失败/泄露定位](necessity-three-arm-holdout/failure-and-leak-diagnostics.json)
- [完整后续轨迹压缩包清单](artifacts/2026-11-23/ARCHIVE_MANIFEST.json)

后续原始缓存体积较大，采用无损压缩保留。报告和任务可直接在线读；完整重放先解包：

```bash
python3 scripts/extract_research_archives.py --all
python3 scripts/verify_current_progress.py --replay
python3 -m unittest discover -s tests -v
```

这些命令不调用模型API。单独做元数据/冻结检查可运行 `python3 scripts/verify_current_progress.py`；发布内容及压缩包秘密扫描为 `python3 scripts/secret_scan.py`。详细行为、异常前缀、预算与重跑限制见[当前复现指南](docs/CURRENT_REPRODUCIBILITY.md)。

## 研究与历史边界

当前主线是动态必要性、交付重验证和不扩权恢复。字段裁剪之外的通用精度、接收方/输出控制、自然语言可靠授权编译、句柄强替代及真实服务并发仍需研究。

更早本地Qwen3-1.7B-4bit实验有明显成功率代价；普通任务里强模型自行按需已经零多读。历史结果、失败和混杂实验全部保留，不与新题混算。[2026-11-19完整快照说明](docs/history/README-20261119-SNAPSHOT.md)、[历史复现指南](docs/REPRODUCIBILITY.md)。

事前给齐只是消融基线；另有含可信最小化、隔离和用户升级的[AirGap架构适配实验](airgap-escalation-state-study/REPORT.md)，也不是原论文精确复现。既有AirGapAgent和工具权限/信息流工作不能被简化掉；定位见[研究方案](docs/PAPER_IDEA.md)。

## 数据、凭据与许可

全部业务资料为合成数据，操作在模拟后端完成。模型权重、API密钥、认证头、内部端点和私有配置不提交。完整合成值匹配不覆盖部分值、语义推断或隐藏推理。

上游AirGapAgent-R数据与派生材料按[第三方声明](THIRD_PARTY_NOTICES.md)标注；原有许可状态保留，本次未替作者选择新的原创代码许可证。当前发布字节见 `PUBLICATION_MANIFEST.json`；历史执行指纹仍按各阶段说明解释。

发布时完成49项机制/计分测试、7项归档辅助安全检查、四阶段全量缓存重放与独立重算。[本次复核记录](artifacts/checks-20261124/verification-summary.json)。
