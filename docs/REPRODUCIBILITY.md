# 复现、配置与公开快照验证

## 两套指纹不能混淆

实验时的`freeze.json`固定的是当时原始代码、数据与模型字节。公开副本删除内网端点、规范化路径并加入配置适配后，部分字节变化。历史哈希仍作为执行证据保留，但不会与改过的公开源码相等。

`PUBLICATION_MANIFEST.json`是本次脱敏发布的字节清单；`PUBLICATION_CHANGES.json`记录原始SHA、发布SHA和改动原因。三个主实验入口的`verify()`仅改为调用便携公开快照验证，评分和消息构建语义保持不变。

## 1. 标准库离线核验，无需API、模型或GPU

在仓库根目录运行：

```bash
python scripts/secret_scan.py
python scripts/verify_artifacts.py
```

第二条检查全部发布文件，再从最新原始轨迹重新计算主指标，与保存的summary逐组比较。不生成新模型回答，也不使用模型裁判。

## 2. 安装运行环境

建议Python 3.11。完整消息重放需tokenizer依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

本地生成还需Apple Silicon、可访问的Metal GPU，以及：

```bash
pip install -r requirements-local.txt
```

原环境：MLX 0.32.4、mlx-lm 0.32.2、Transformers 5.23.0、tokenizers 0.23.3、huggingface-hub 2.4.0、NumPy 2.4.6。没有Torch也可以执行本仓库使用的MLX推理；纯离线重算不需要这些依赖。

## 3. 模型文件放在仓库外或被忽略目录

原模型来自`mlx-community/Qwen3-1.7B-4bit`。自行依照提供方许可获取，并设置：

```bash
export LOCAL_MODEL_PATH="$PWD/models/Qwen3-1.7B-4bit"
```

原`model.safetensors`共968,080,210字节，SHA-256为`0e86d9677e519323849eac1bc272caae88567a481ff188c431f70be543d9995f`。仓库没有权重。仅重放消息需要原tokenizer JSON及配置；生成需要完整匹配权重。提供方后续main分支可能改变，应该核对指纹，不假定同名等于同版本。

## 4. 完整输入/事件重放

```bash
python state_holdout_cross_model.py audit
```

它不请求MaaS、不生成回答。通过保存的原始输出重建每次输入，核对哈希、token数量、工具事件、操作和恢复。原审计共核验27,065次模型输入。

历史`blind_three_arm_replay.py`、`tool_channel_failure_retest.py audit`为不同实验各自的重放入口，不要混用其分母或任务集。

## 5. 重新推理：另建输出目录

不要覆盖归档轨迹。最新任务已经冻结并提供，不需要再次运行prepare来造同一批题。

```bash
python scripts/run_latest.py --model local-qwen3-1.7b --out runs/reproduction
```

MaaS需自己配置一个兼容服务。不要把真实URL、密钥或私有配置写回仓库：

```bash
export QWEN_MAAS_URL='<your-own-compatible-endpoint>'
python scripts/run_latest.py --model qwen3.8-flash \
  --out runs/reproduction --key-file /path/outside-repository/credential-file
```

服务必须实际提供该模型或由你明确适配；本仓库不包含原公司服务地址，也不保证公开服务存在同名模型。API请求的模型别名、返回版本、usage、finish reason应一并保存。不要把换提供商后的结果说成原服务精确复现。

运行器温度0.3、192输出token、24轮、请求关闭推理；模型自行调用工具，最多两次相同停顿恢复。重跑有采样/浮点差异，不保证逐字一致。`runs/`被Git忽略。

## 6. 汇总重跑结果

归档结果本身已提供summary和报告。若两模型都已在同一独立输出目录跑完：

```bash
python - <<'PY'
from pathlib import Path
import state_holdout_cross_model as e
e.ROOT = Path('runs/reproduction').resolve()
e.audit()
e.summarize()
PY
```

便携`verify()`验证发布源，不把新生成结果伪称为原冻结结果。新结果应与原报告分别存放。

## 7. 历史数据与入口

AirGapAgent-R原数据位于`data/source/airgapagent-r.json`；旧脚本`--dataset`参数可指向它。原文件4,160条、版本标识f1d8f27、哈希见第三方声明。历史holdout JSON仅保存源索引或派生任务，不能替代源数据。

每轮代码与原说明保留原相对位置，方便检查导入。早期README移至`docs/history/FIRST-ROUND-README.md`。旧文档中的临时路径只是历史运行示例；当前统一以环境配置和本指南为准。

## 8. 安全发布约定

不跟踪`.env`、密钥、缓存、模型权重、虚拟环境或新生成runs。`.env.example`只有空变量名，不自动加载、不包含任何可用配置。API密钥只从外部文件读取，HTTP头不写入轨迹。

扫描通过只表示未匹配检查规则，不能保证识别世界上所有秘密。公开之前仍应检查暂存区、git历史、数据归属及主张边界。
