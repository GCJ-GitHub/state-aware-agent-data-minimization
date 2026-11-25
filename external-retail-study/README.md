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
