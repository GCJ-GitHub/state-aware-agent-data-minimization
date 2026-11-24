# 后续实验完整轨迹

根级报告、任务、评分和协议直接放在各阶段目录。下面四个压缩包保留原始相对路径和文本字节，包含正式轨迹、开发诊断、HTTP元数据和中断；不是抽样或重新生成的回答。

| 阶段 | 文件数 | 原始MiB | 压缩MiB | 文件 |
|---|---:|---:|---:|---|
| `airgap-escalation-state-study` | 7899 | 55.97 | 2.99 | [下载](airgap-escalation-state-study.traces.tar.gz) |
| `necessity-factorial-pilot` | 1737 | 20.65 | 1.02 | [下载](necessity-factorial-pilot.traces.tar.gz) |
| `necessity-native-retest` | 1693 | 44.63 | 2.05 | [下载](necessity-native-retest.traces.tar.gz) |
| `necessity-three-arm-holdout` | 12943 | 369.41 | 18.64 | [下载](necessity-three-arm-holdout.traces.tar.gz) |

SHA-256、允许路径前缀和字节统计见 [ARCHIVE_MANIFEST.json](ARCHIVE_MANIFEST.json)。包内不含权重、认证配置或API凭据。凭据扫描同时解压检查成员文本，不是仅跳过二进制压缩包。

在仓库根目录运行 `python3 scripts/extract_research_archives.py --all`。只允许普通相对路径文件，拒绝符号链接/路径穿越、重复成员、非声明前缀、大小或哈希不符；已存在但字节不同的文件不会被覆盖。

完整流程见[复核指南](../../docs/CURRENT_REPRODUCIBILITY.md)。
