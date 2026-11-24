# 必要数据推导原型：离线检查

**这是脚本和单元测试结果，不是 Agent / MaaS 对照实验。模型调用为 0。**

12 个脚本例子，27 项单元测试通过；计划候选集与独立子集枚举器在 64 个完整状态/策略配置上一致。

| 脚本场景 | 从工具依赖推导的执行字段 | 实际给脚本的原值字段数 | 后端判断查询读取的原始字段次 | 放出的判断结果数 |
|---|---|---:|---:|---:|
| refund_wallet | order.wallet_ref | 1 | 0 | 0 |
| refund_bank_normal | customer.owner_ref, order.account_ref | 2 | 0 | 0 |
| refund_bank_high_value | customer.identity_ref, customer.owner_ref, order.account_ref | 3 | 0 | 0 |
| user_prefers_bank_over_less_data | customer.owner_ref, order.account_ref | 2 | 0 | 0 |
| user_requests_exact_quotes | order.wallet_ref, private.bank_fee, private.wallet_fee | 3 | 0 | 0 |
| two_appointments_shared_identity | customer.identity_ref, session1.member_ref, session2.member_ref | 3 | 0 | 0 |
| two_appointments_home | customer.identity_ref, session1.address_ref, session1.member_ref, session2.address_ref, session2.member_ref | 5 | 0 | 0 |
| refund_predicate_then_execute | order.wallet_ref | 1 | 2 | 1 |
| delivery_radius_True | parcel.postal_ref | 1 | 1 | 1 |
| delivery_radius_False | parcel.address_ref, parcel.contact_ref | 2 | 1 | 1 |
| delivery_skip_unnecessary_private_probe | parcel.address_ref, parcel.contact_ref | 2 | 0 | 0 |
| replan_after_better_route_appears | order.wallet_ref | 1 | 0 | 0 |

## 查询顺序的小例子

只有两个获准的独立查询：费用是否达标、时效是否达标。两者都达标才走少一个执行字段的钱包路线，否则走银行路线。

在预设独立先验 P(费用达标)=0.1、P(时效达标)=0.9、每次查询代价为 1 时，标准动态规划参考解的期望查询数为 **1.1**，固定先查时效为 **1.9**。数字来自四个真值世界的加权精确计算，不是模型测得的成功率或现实节省。

这验证的是“查询顺序本身可以成为研究变量”。动态规划与短路查询都是已有技术；原型没有证明新的在线算法优于已有方法，也没有把概率当成授权证据。

## 检查覆盖

- 多条合法路线；用户优先级优于省字段；只有明确要求最小化时才强制字段成本最小。
- 同一套基础工具契约推导普通/高额退款的不同依赖，无每订单最终字段答案表。
- 缺少可信证据时等待；不根据模型自称需要或高概率猜测放行。
- 查询只放固定判断结果，但后端真实读取和判断结果披露均计数。
- 共享依赖、每一步放行、越界多取、伪造事实、跨订单复用、重复使用。
- 状态或字段变更后拒绝旧权限；也绑定排除更优路线的负面证据。
- 用户确实要求准确费用时允许原值；不靠拒绝合法任务获得少读。

## 尚未实现

真实 LLM 自主规划、自然语言授权可靠编译、真实服务工具契约、跨进程事务、已成功副作用的跨计划续接、输出信息流隔离、复杂查询或部分值推断防护、可扩展的近似查询算法及独立盲测。已完成副作用后，原型拒绝新计划以避免模拟重复执行，不能当作自动恢复系统。

详见 [研究方案](../docs/RESEARCH_V2.md)。运行：`python3 scripts/run_necessity_prototype.py`。
