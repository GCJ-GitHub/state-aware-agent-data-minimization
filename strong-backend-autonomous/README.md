# 强基线自主对照

本目录保存论文附录所述的合成任务自主对照。每个任务对的两位成员共享用户请求、起始状态、授权和字段值。两位成员采用不同的状态更新方案。三个工作流家族各 20 对，共 120 位任务成员。每位成员运行两个后端，各用三个预设的种子值。

| 文件 | 内容 |
|---|---|
| rules.json | 两个后端的契约与路线配置，以及共用的优先级和确认规则 |
| tasks.json | 冻结的成对任务、时钟安排和业务判定 |
| tools.json、system.txt | 两组共用的工具 schema 与模型提示 |
| protocol.json、freeze.json | 运行配置、冻结哈希和传输修订记录 |
| episodes/ | 正式运行的原始工具轨迹和模型可见文字 |
| transport-trial/ | 调节网关速率之前保存的试跑记录 |
| metrics.json、summary.json | 逐运行指标和配对汇总，由正式运行生成 |
| audit.py、report.py | 离线逐轨迹复核和报告生成 |
| REPORT.md | 完整结果及分场景分析 |

在仓库根目录执行。MaaS 地址通过 STUDY_GATEWAY_URL 传入，凭据由 STUDY_KEY_PATH 指向的仓库外文件读取。Python 需要 requests 和 numpy。

    python strong_backend_autonomous.py run
    python strong-backend-autonomous/audit.py
    python strong-backend-autonomous/report.py

运行按任务、后端和种子逐条保存。中断后再次执行 run 会继续缺失的运行，已有记录保持原样。传输重试只重复同一模型请求。工具执行使用模拟器。测试字段值均为合成文本。
