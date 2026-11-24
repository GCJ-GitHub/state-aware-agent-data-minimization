# 当前代码、原始材料与离线复核

更新：2026-11-24。本页补充[历史指南](REPRODUCIBILITY.md)，优先适用于2026-11-23后续四个自主模型阶段和必要性原型。不请求模型，也不需要GPU、权重、MaaS权限或模型裁判即可核对保存结果。

后续四轮强基线的独立复跑命令见[四轮对照复跑](STRONG_BASELINE_FOLLOWUP.md#离线复跑)。

## 1. 安装要求

推荐Python 3.11；后续核心、解包和离线重放使用标准库。单元测试也不请求模型API。历史MLX本地生成、tokenizer重放及上游数据说明仍按历史指南。

## 2. 先检查发布文件

```bash
python3 scripts/secret_scan.py
python3 scripts/verify_current_progress.py
python3 scripts/verify_artifacts.py
```

- 秘密扫描会检查普通文本和声明压缩包内的每个UTF-8成员，并核验压缩包SHA-256、路径、成员数量和大小；不打印匹配到的秘密值。
- 当前验证检查发布字节、后续原始冻结源码/输入和正式分母。
- 历史验证从原有跨模型材料重算原主结果，不把旧结果混入新题。

`PUBLICATION_MANIFEST.json`校验当前公开文件；各阶段 `freeze.json` 固定实验当时的源码和输入。后续新增实验源码本次按原字节发布，所以其冻结检查应直接通过；原有早期脱敏代码仍按历史便携验证说明。新的归档方式只改变存储容器，不改原始轨迹字节。

## 3. 解包完整轨迹

```bash
python3 scripts/extract_research_archives.py --list
python3 scripts/extract_research_archives.py --all
```

也可只解一个阶段：

```bash
python3 scripts/extract_research_archives.py --study necessity-three-arm-holdout
```

默认恢复到仓库根目录，`episodes/`、开发目录等路径与原运行一致。解包不执行任何成员代码，拒绝覆盖不同内容文件。`--out /path/to/another-directory` 可另存，但现有审计入口默认从仓库根级阶段目录读；另存后需自己设置等价ROOT，不能把找不到轨迹误当零数据。

压缩包共24,272个原文件；[清单](../artifacts/2026-11-23/ARCHIVE_MANIFEST.json)包含逐包统计。原始任务、答案/夹具、指标、报告和冻结文件不需要解包即可在线阅读。解出的原始目录被Git忽略，以免把同一材料再提交一遍。

## 4. 全量离线复核

```bash
python3 scripts/verify_current_progress.py --replay
python3 -m unittest discover -s tests -v
```

复核依次运行：

| 阶段 | 原始请求/动作重放 | 独立事件重算 |
|---|---|---|
| AirGap架构适配 | `python3 airgap_state_study.py audit` | `python3 scripts/check_state_study_results.py` |
| 2×2试验 | `python3 necessity_factorial.py audit` | `python3 scripts/check_necessity_factorial_results.py` |
| 原生工具同题重测 | `python3 necessity_native_retest.py audit` | `python3 scripts/check_necessity_native_results.py` |
| 新120题三组 | `python3 scripts/audit_holdout_with_interruptions.py` | `python3 scripts/check_necessity_holdout_results.py` |
| 新题状态/呈现 | 上述请求重放 | `python3 scripts/check_holdout_state_ledger.py` |

每项输出写到本地 `artifacts/verification/`，失败即停止；不会把失败跳过继续宣称全部通过。上表验证导入的是已发布原始实现，回答来自保存缓存，不产生新回答。当前49项单元测试为机制和计分检查，不是49个模型任务。

## 5. 异常轨迹怎样复核

新120题有一条HTTP400，在25次真实模型回复后中断，业务已完成但无正常最终回答。`audit_holdout_with_interruptions.py`只恢复已观察前缀，离线重放边界是缓存长度，正式模型预算仍40；不会伪造第26条回复或替模型执行。`result.json`、`interruption.json`、重建的失败请求及前缀元数据均保留。

另一条HTTP429在3条已缓存回复后限流，随后从同一请求继续。请求和错误记录也保留，不能把HTTP重试当额外模型回复或把原中断删掉。

因此不要对新120题直接套普通 `necessity_holdout.py audit`：它假设所有轨迹自然结束，不处理这条异常前缀。应使用上表专用入口。业务成功、正常文字收尾、原值交付与最终回答隐私分别看对应指标。

## 6. 开发材料与正式结果

压缩包中的开发格式诊断、原生ping探测和机械测试不能混入正式主表。四个后续正式阶段分别648、144、144、1080；同题重测与新留出也不能混作独立任务。

报告文件记录各轮统计口径。重新运行报告脚本可能重写解释性附注，建议先复制到独立工作目录；本页复核主要检查缓存/指标，不要求覆盖现有报告。所有模型相关源码、任务与冻结指纹均保留。

## 7. 如果确实需要重新调用模型

本次整理没有产生新模型调用。后续运行器有 `run` 模式，配置从仓库外JSON读取，形如：

```json
{"endpoint": "<your-compatible-endpoint>", "api_key": "<your-credential>"}
```

不要把这个文件放进仓库。服务必须支持脚本所用模型、请求预算与原生工具协议；同名模型别名不是权重指纹。

已有轨迹目录有缓存，直接运行 `run` 可能复用已有回答，不能称作新实验。重新推理应在独立checkout/输出目录操作，核验冻结输入、固定新输出位置并保留每个中断；不要清除本归档目录追求好看的主表。历史 `scripts/run_latest.py --out runs/...` 属于旧跨模型实验，不是新120题运行器。

## 8. 本次发布范围与隐私

后续核心/运行/报告/检查源码，任务、独立答案/夹具，全部评分和报告，四个完整原始轨迹压缩包以及测试均发布。未发布模型权重、外部运行配置、API密钥、认证头、内部服务地址与个人绝对路径。

压缩包内资料为合成字段与模拟业务操作。完整值匹配不等于所有信息泄露检测；零匹配不能证明部分值、语义推断或隐藏推理安全。没有替原作者选择新的原创代码许可证，第三方许可按原声明保留。

发布时的复核日志见[checks-20261124](../artifacts/checks-20261124/verification-summary.json)。归档辅助安全检查可单独运行 `python3 scripts/check_research_archive_safety.py`；它与49项核心测试分开，不计入模型实验。
