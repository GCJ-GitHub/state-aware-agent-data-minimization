# 第五轮物流实验

用第四轮相同的模型、模拟后端、工具、解码设置和订单重跑 24 单，逐单对比第四轮日志。

当模型没有给出可解析的工具调用、后端已经准备好路线、所需字段已实际进入模型输入，且业务尚未完成时，追加一次提示。提示要求模型依据工具定义重新输出完整的工具名和参数，并使用已得到的值。提示不包含具体工具名、参数值或可直接执行的调用。解析器和后端继续对模型回复做原有检查。每单最多提示一次，重试计入原有推理轮次预算。

```sh
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python round5.py \
  --model /path/to/Qwen3-1.7B-4bit \
  --round2-trace results-round2/traces.jsonl \
  --round4-trace results-round4/traces.jsonl \
  --out results-round5
```

`results-round5/summary.json` 汇总工具调用和模型推理轮数的配对差值，`results-round5/traces.jsonl` 保留模型原始输出、重试轮次和实际执行结果。耗时跨两次运行比较，会受本机负载影响。

## 实测结果

| 每组 24 单 | 第四轮 | 第五轮 |
| --- | ---: | ---: |
| 任务成功 | 23 | 24 |
| 发生过度暴露 | 0 | 0 |
| 工具调用总数 | 100 | 101 |
| 平均每单工具调用 | 4.17 | 4.21 |

仅 52 号触发提示。模型用一次额外推理生成了完整的 execute_route 调用，正确提交自提路线和已取到的邮编，后端确认成功。该单从 4 次工具调用增加到 5 次。其余 23 单的模型输出和实际调用轨迹逐条一致。
