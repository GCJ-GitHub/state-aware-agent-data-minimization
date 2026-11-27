# τ-bench 零售工作流迁移对照

此轮使用 Sierra τ-bench 零售测试集和工具执行器的固定提交。代码、上游数据哈希、派生任务、三组协议、逐条轨迹和计分都保存在此实验里。原始 τ-bench 源码和完整数据库由上游仓库提供。

## 离线复放

在仓库根目录使用已安装 [requirements.txt](../requirements.txt) 依赖的 Python 环境执行。

```bash
python scripts/extract_research_archives.py --study external-retail-study
git clone https://github.com/sierra-research/tau-bench.git ../tau-bench
git -C ../tau-bench checkout 59a200c6d575d595120f1cb70fea53cef0632f6b
python external_retail_study.py verify --upstream ../tau-bench
python external_retail_study.py summarize
python external-retail-study/report.py
```

上述命令用缓存轨迹离线生成审计和计分报告。重新调用模型时，在独立输出目录运行，并由 STUDY_GATEWAY_URL 提供服务地址、STUDY_KEY_PATH 提供仓库外的一次性凭据文件。运行器读取后删除该临时凭据。实验使用公开基准的合成资料和模拟地址。对照结果采用研究自定义的字段暴露和业务后置条件，原 τ-bench 评测采用自身任务与计分协议。

## 引言中的回放轨迹

论文图 1 使用 Qwen4-Max 在任务 `tau-retail-route_switch-01-event`、种子 `19` 上的两条轨迹。两条都在[完整轨迹归档](../artifacts/2026-11-23/external-retail-study.traces.tar.gz)中。请从仓库根目录执行以下命令，每条命令输出一份 JSON。

```bash
tar -xOzf artifacts/2026-11-23/external-retail-study.traces.tar.gz \
  external-retail-study/episodes/tau-retail-route_switch-01-event__agent_only__19.json
tar -xOzf artifacts/2026-11-23/external-retail-study.traces.tar.gz \
  external-retail-study/episodes/tau-retail-route_switch-01-event__contract__19.json
```

两次运行都在第 2 轮准备读取地址。第 3 轮，模拟环境在回包前将订单标记为已送达。

| 图 1 面板 | 第 3 轮地址回包 | 后续操作 | 业务结果 |
| --- | --- | --- | --- |
| (a) 自行按需 | 六个地址原值进入模型上下文 | 第 4 轮改址确认被拒，第 5 轮重新查状态 | 第 10 轮提交退货 |
| (b) 交付前校验（契约后端） | 六个地址原值全部拦下，工具返回重规划提示 | 第 4 轮重新查状态 | 第 9 轮提交退货 |

运行[离线复放命令](#离线复放)可用固定版本的上游工具核验缓存调用及业务结果。三组共 270 次运行，每组均为 90/90 个正确结果。自行按需组累计多读 270 个字段次，两种后端均降到 0。

[实验运行器](../external_retail_study.py) · [派生任务](tasks.json) · [冻结协议](protocol.json) · [逐条计分](metrics.json) · [汇总报告](REPORT.md)
