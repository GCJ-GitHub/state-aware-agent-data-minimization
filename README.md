# 状态感知 Agent 数据最小化：方法、代码与实验

更新：**2026-11-27**。

## 论文主线

**任务办对了，数据却多给了。** 在一次 τ-bench 零售回放中，Agent 准备读取收货地址时，订单还可以改址。工具返回前，模拟环境把订单标记为已送达。Agent 后来正确办了退货，但六个已经用不上的地址字段仍随旧请求进入了模型上下文。用户授权没有变化，变化的是这一步取数的理由。

**图 1** 并排展示同一任务、同一种子的两条轨迹。第 3 轮，自行按需组把六个地址原值交给模型，交付前校验组拦下了这些值。两组都办成了退货，分别在第 10 轮和第 9 轮。 [图 1 预览](paper/figures/tau-bench-return-trace.png) · [SVG 矢量稿](paper/figures/tau-bench-return-trace.svg)

论文研究如何在原值进入模型前重验当前路线、步骤条件和字段必要性。读取被拒绝时，连接器在反馈中提供拒绝原因和可继续的选项。Agent 自行调用工具刷新状态、调整路线、复用仍有效的核验和已完成事项，或者在没有授权路线时安全停止。

[论文 PDF](paper/paper.pdf) · [LaTeX 源码](paper/paper.tex) · [图 1 实验轨迹与离线复放](external-retail-study/README.md#引言中的回放轨迹) · [实验代码](external_retail_study.py) · [结果与计分](external-retail-study/REPORT.md)

## 从图 1 到四项交付前检查

图 1 中，Agent 在第 2 轮为改址准备读取地址。第 3 轮回包前，订单变成已送达。请求仍指向同一订单，但改址路线已经失效。连接器用交付时的状态检查下列四项。

| 检查 | 交付前要确认什么 | 公式（6）中的条件 |
| --- | --- | --- |
| 请求范围 | 请求与准备读取时的订单、计划会话和步骤一致 | `Scope(r,s,a)` |
| 当前路线 | 当前业务证据仍支持这条路线，且路线符合用户授权和偏好 | `p_s ∈ A_t` |
| 步骤可执行 | 该步骤仍待执行，前置条件和适用的确认均已满足 | `Enabled_t(s,a)` |
| 字段必要性 | 请求的字段恰好是这一步仍缺的输入。公式（5）定义这个字段集合 | `S = D_t(a)` |

**算法 1** 在工具回包前获取当前状态，执行公式（6）的四项检查。契约后端还要用公式（8）验证读取凭证。第 3 轮改址路线失效，第二项已足以拦下地址原值。**算法 2** 描述 Agent 收到拒绝后怎样刷新状态、另选获准的退货路线并读取所需字段。钱包退款例子用于说明凭证版本绑定，以及换路线后何时可以复用核验记录。 [方法正文与伪代码](paper/method.tex)

## 三项贡献

1. **定义交付时的字段必要性。** 把授权、路线偏好、当前状态和步骤前置条件统一到连接器的读取判定。
2. **实现两种后端与同一条恢复路径。** 可组合路线表和契约后端都能在原值交付前刷新并校验。窄绑定契约保留授权撤回代数和所需字段版本，当前路线仍在交付前检查。两种后端均由 Agent 自行恢复。
3. **测量减曝效果和恢复代价。** 两个模型及 τ-bench 零售工具环境复现了交付校验的效果。在直接对照中，两种后端都做到零多读。Qwen4-Max 强基线中，仅证据版本变化而路线仍合法时，版本绑定额外触发 90 次读拒绝，增加 360 次业务结束前的工具调用。

## 实验正文的三个问题

| 问题 | 现有实验给出的答案 | 数据与复放 |
| --- | --- | --- |
| **RQ1. 任务做对了，模型还会多读吗？** | τ-bench 受控零售回放中，三组各有 **90/90 个正确结果**，其中各含 15 次预期安全停止。自行按需组仍多交付 **270 个字段次**，交付前校验的路线表和契约后端均降到 **0**。这里计的是原值进入模型上下文。 | [零售对照与复放](external-retail-study/REPORT.md) |
| **RQ2. 为什么要在交付前校验？** | Gaia2 的 7 个匹配三元组中，自行按需和只在读准备时刷新的路线表各交付 **7 次**过期回包，交付前校验的契约组为 **0 次**，三组均 **7/7** 通过。让路线表也在交付前刷新后，8 个命中窗口的匹配对中两组都拦住旧值，任务通过分别为 **8/8 和 6/8**，切换后工具调用分别为 **59 和 58**。 | [交付窗口](independent-holdout/gaia2/delivery-window/README.md) · [交付前刷新路线表](independent-holdout/gaia2/delivery-refresh/README.md) |
| **RQ3. 契约的恢复代价能降下来吗？** | Qwen4-Max 强基线对照中，证据版本变化而路线仍有效的 90 次运行让原契约多触发 **90 次拒绝、360 次业务结束前调用**。退款复测中，窄绑定消除 **3 次误拒绝和 12 次额外调用**，与强路线表逐对一致。三组均 **15/15 成功、0/9 误放行**。 | [强基线复现](qwen4-max-paper-replication/REPORT.md) · [退款三组复测](refund-state-return-study/selective-contract/README.md) |

[实验正文 LaTeX](paper/evaluation.tex) · [附录 LaTeX](paper/evaluation-details.tex) · [Gaia2 与退款明细表](paper/timing-refund-details.tex)

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
