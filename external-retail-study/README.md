# τ-bench 零售工作流迁移对照

此轮使用 Sierra τ-bench 零售测试集和工具执行器的固定提交。代码、上游数据哈希、派生任务、三组协议、逐条轨迹和计分都保存在此实验里。原始 τ-bench 源码和完整数据库由上游仓库提供。

```bash
python scripts/extract_research_archives.py --study external-retail-study
git clone https://github.com/sierra-research/tau-bench.git ../tau-bench
git -C ../tau-bench checkout 59a200c6d575d595120f1cb70fea53cef0632f6b
python external_retail_study.py verify --upstream ../tau-bench
python external_retail_study.py summarize
python external-retail-study/report.py
```

上述命令只读取已有轨迹。重新调用模型时，在独立输出目录运行，并由 STUDY_GATEWAY_URL 提供服务地址、STUDY_KEY_PATH 提供仓库外的一次性凭据文件。运行器读取后删除该临时凭据。实验使用公开基准的合成资料和模拟地址。对照结果采用研究自定义的字段暴露和业务后置条件，原 τ-bench 评测采用自身任务与计分协议。

## 引言中的回放轨迹

论文开头使用的是自行按需组的 `tau-retail-route_switch-01-event`，种子为 `19`。该条轨迹已随[完整轨迹归档](../artifacts/2026-11-23/external-retail-study.traces.tar.gz)发布，可以单独查看。

```bash
tar -xOzf artifacts/2026-11-23/external-retail-study.traces.tar.gz \
  external-retail-study/episodes/tau-retail-route_switch-01-event__agent_only__19.json
```

第 2 轮准备取地址。第 3 轮模拟环境将订单标记为已送达，工具仍向模型返回了六个地址字段。第 4 轮改址确认被拒绝，Agent 随后重新查状态并转为退货，第 10 轮提交退货。这条轨迹同时满足业务成功和字段多读。三组共 270 次运行，各组均为 90/90 个正确结果；两种后端均将相对自行按需组的 270 个多读字段次降到 0。

[实验运行器](../external_retail_study.py) · [派生任务](tasks.json) · [冻结协议](protocol.json) · [逐条计分](metrics.json) · [汇总报告](REPORT.md)
