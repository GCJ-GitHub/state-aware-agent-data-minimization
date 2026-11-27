# 独立出题验证 · 公开案例筛选

筛选覆盖 Gaia2 Adaptability 的 160 道验证题和 SentinelBench 的 100 道正式题，并核对了 Async-RBench 的公开发布范围。尚未筛出能沿用上游时序、直接对照原值交付前校验的任务批次。本轮模型运行数为 0。

## Gaia2 Adaptability

上游同时提供用户请求、业务事件和预期写操作。按 `event_id` 解析验证集的依赖图后，160 道题都包含环境事件及 `OracleEvent`。380 个环境事件的直接前置动作都是 `AgentUserInterface.send_message_to_user`，环境在 Agent 向用户汇报某一步之后才触发对应变化。这里按数据中的依赖关系计数。上游以预期写操作及其顺序判分，允许 Agent 通过不同读取路径取得所需信息。 [数据](https://huggingface.co/datasets/meta-agents-research-environments/gaia2/tree/c128283/adaptability) · [上游判分说明](https://facebookresearch.github.io/meta-agents-research-environments/foundations/scenarios.html)

| 上游案例 | 业务变化 | 与本研究的对应关系 |
| --- | --- | --- |
| `0603` · `scenario_universe_29_jremqj` | 首次使用折扣码完成结账并汇报后，上游取消订单。之后应按原价规则调整购物车并重新下单。 | 原优惠码在后续阶段不再需要。取消发生前首次结账已经使用过折扣码。这适合检验切换后能否停止重新读取旧字段，以及能否完成后续流程。 |
| `0606` · `scenario_universe_23_tbrkm7` | Agent 先保存房源、安排看房并汇报。联系人回复后，Agent 要替换房源并改约。 | 外部作者定义了两阶段的不同目标。原始案例没有安排旧房源的字段请求跨越回复事件后才交付。 |
| `0630` · `scenario_universe_23_z1qeie` | 订车并汇报后，车辆状态改成延迟。Agent 应取消原车，再联系可能提供接送的人。 | 可检验能否从订车转到通知。上游判分可核对取消和通知，旧字段何时从工具返回需要额外追踪。 |

数据文件为 `adaptability/validation-00000-of-00001.parquet`，快照 `c128283`，文件 SHA-256 为 `e449bf40b5dbb26df844c23c62e8ea94ee313ea6dd13d4aedb730fd8c1a6230e`。可复核方法是逐行解析 `data.events`，按 `event_type == "ENV"` 计数，并通过 `dependencies` 逐个解析直接前置动作。统计描述的是上游编排的环境事件，不能排除自主运行时 Agent 偶然发出跨越事件的读取。

## SentinelBench 和 Async-RBench

- **SentinelBench** · 快照 `3fa7634e114c8d223f8f2e54464be1fadbd8c7a6`。读取 `scenarios/*/*.json` 并排除 `dev.json`，得到 10 个环境各 10 题，80 道提供非空 `eval_sql`。事件类型以增加消息、记录或提醒为主，也有指标到达阈值。比如日历的 analytics 题要求打开描述检查关键词，查看候选记录是任务的一部分，不能因为某条记录未命中就将读取算作多读。筛选未找到原始事件专门使一项待交付的字段失效。 [任务与事件定义](https://github.com/microsoft/sentinel_environments/tree/3fa7634e114c8d223f8f2e54464be1fadbd8c7a6/scenarios)
- **Async-RBench** · 快照 `56c25554768a7eeb9b493361f4243ef330dbff8b`。公开发布有 200 道题，覆盖过期结果、途中取消等问题。部分案例含应用内事件数据，例如 Stockholm Move-Out 的房源流。正式的异步事件调度、隐藏测试和评分逻辑要从单独分发的评测包获得，只有公开版无法同时复用完整的上游时序与正式评分。 [发布说明](https://github.com/pope8zdt/Async-RBench#dataset) · [评测协议](https://github.com/pope8zdt/Async-RBench/blob/main/docs/protocol.md)

## 两种可以独立报告的验证

1. **验证在上游业务流程中的表现。** 保留 Gaia2 的用户请求、事件依赖和业务判分，按任务文字及工具字段定义预先标注切换后的字段需要。三组共享原始任务、授权、确认、恢复、工具格式与预算。以每组每题三次配对运行，报告事件触发后的多读、成功率和额外调用，同时保留全量分母。旧流程在变化前已经合理取得的值不计为多读。字段判分属于本研究的测量层，应与上游业务判分分别报告。
2. **验证原值即将交付时的失效。** 需要能复现一个具体顺序。Agent 先启动取数，随后上游事件改变业务条件，工具最后才尝试交付原值。若通过给公开案例额外加入延迟来复现，应单列为基于公开任务的时序压力测试，公开自加的延迟以及实际命中该时间窗口的运行数。这个结果的独立性覆盖上游业务题和判分，交付时序由本研究设计。

两种验证都将 Agent 自行按需、读前刷新路线表、契约后端作为三组。判分器及预期答案留在评测侧。一次正常重选路线也可能需要额外调用，费用应区分事件后的恢复、后端拒绝后的恢复以及任务结束后的回复。
