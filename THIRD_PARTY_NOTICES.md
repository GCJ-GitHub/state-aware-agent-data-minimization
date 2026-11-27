# 第三方数据与文献

## AirGapAgent-R

- 作者/发布方：Parameter Lab；Tommaso Green、Martin Gubri、Haritz Puerto、Sangdoo Yun、Seong Joon Oh。
- 数据集：<https://huggingface.co/datasets/parameterlab/leaky_thoughts>
- 项目：<https://github.com/parameterlab/leaky_thoughts>
- 论文：*Leaky Thoughts: Large Reasoning Models Are Not Private Thinkers*，<https://arxiv.org/abs/2506.15674>。
- 上游数据卡在本次打包时声明许可：Open Data Commons Attribution License（ODC-By），<https://opendatacommons.org/licenses/by/1-0/>。
- 数据卡：<https://huggingface.co/datasets/parameterlab/leaky_thoughts/blob/main/README.md>。
- 本实验使用版本标识：`f1d8f27`，4,160条。原文件为`airgapagent-r.json`；本仓库保存于`data/source/airgapagent-r.json`。
- 原字节SHA-256：`117a76be7caa1e0cde682a0f594fb70af8c6e6859041bc8a5b39c48b22bdf3e3`。

上游数据原样保存。基于它构造的状态切换、诱导文本、字段授权和结果属于本研究的衍生实验设置；没有把这些设置说成原公开榜单。相关`orders-airgap-r-*.json`、`results-airgap-r*`和MaaS早期结果应连同此署名、来源及上游许可声明保留。

## AirGapAgent

Eugene Bagdasarian、Ren Yi、Sahra Ghalebikesabi、Peter Kairouz、Marco Gruteser、Sewoong Oh、Borja Balle、Daniel Ramage. *AirGapAgent: Protecting Privacy-Conscious Conversational Agents*. ACM CCS 2024, 3868–3882. DOI: <https://doi.org/10.1145/3658644.3690350>；预印本：<https://arxiv.org/abs/2405.05175>。

本仓库不包含论文PDF，不声称包含原作者未发布的原始基准或完整原版实现。AirGapAgent-R是后续研究者的重建。

## 模型与依赖

本仓库不分发模型权重、二进制运行环境或第三方软件源码。模型、MLX、Transformers及各服务遵守其自身许可/条款。实验本地模型来自`mlx-community/Qwen3-1.7B-4bit`；服务端别名仅用于记录实际实验，不表示其在其他提供商可用。

## 原创材料

原创代码、非上游数据生成的物流/退款/预约模拟任务及研究说明归仓库作者管理。尚未为这些材料指定通用开源许可证，不以本声明替代所有者的许可选择。第三方数据继续使用其自身声明。

## Gaia2 Adaptability

实验使用 Meta Agents Research Environments 发布的 [Gaia2 Adaptability validation 数据](https://huggingface.co/datasets/meta-agents-research-environments/gaia2/tree/c128283/adaptability)，公开数据卡标注 CC BY 4.0。上游任务、模拟应用数据、事件和原生业务判分归上游。完整验证集的源文件、版本和 SHA-256 见[数据说明](independent-holdout/gaia2/DATA.md)。随仓库发布的是任务索引与本研究的结果、事件命中统计和工具名轨迹。受控交付窗口和字段评分由本研究定义。官方 ARE 运行器从其上游仓库按固定提交安装。
