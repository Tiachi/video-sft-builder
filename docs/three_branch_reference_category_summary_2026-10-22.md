# 三管线：96个分类组、题数、筛选与缺口

日期：2026-10-22；这是本地官方标注的固定版本统计，不是模型构造数据的通过率。设计与来源见[三管线说明](three_branch_caption_qa_design_2026-10-22.md)，完整原题表在本地 `x_temp/qa_reference_three_branches_20261022_v3/all_qa_examples.md`（代码库外，不上传Public）。

## 汇总

| 管线 | 参考池 | 请求分类数 | 条件保留分类 | 整类暂缓 | 入表QA行数 |
|---|---|---:|---:|---:|---:|
| General | Video-MME全量2700题 | 12 | 10 | 2 | 100 |
| General | Video-MME-v2全量3200题 | 33 | 21 | 12 | 207 |
| Long | Video-MME long子集900题 | 12 | 10 | 2 | 82 |
| Long | LVBench 1549题，多标签2094次归类 | 6 | 6 | 0 | 60 |
| Knowledge | Video-MMMU三轨道合计900题 | 6 | 1 | 5 | 10 |
| Knowledge | MMVU公开validation 1000题 | 27学科 | 27学科逐题判断 | 0整科 | 267 |
| 总计 | long子集不是额外独立数据集 | **96** | **75** | **21** | **726** |

726行中有**695道独立原题**：22道原题同时选入General和Long，另外9次是LVBench同一题在多个真实标签下出现。不是726个独立原题，也未改写/重造答案。70个条件保留组各10题，剩余5组不足10题。

| 不足的组 | 源题数 | 筛后可选/入表 | 缺口 |
|---|---:|---:|---:|
| General / v2 / Entity Existence Change Detection | 62 | 7 | 3 |
| Knowledge / MMVU / History | 10 | 7 | 3 |
| Long / Video-MME / Spatial Perception | 3 | 1 | 9 |
| Long / Video-MME / Spatial Reasoning | 11 | 8 | 2 |
| Long / Video-MME / Temporal Perception | 6 | 3 | 7 |

`conditional`=该能力可按证据条件参考，逐题仍需视频/caption确认；`deferred`=首版暂缓并另列专项。静态候选通过只代表没有命中当前文本排除规则，不代表已证明caption可答。类别过滤是本项目保守决策，不是论文对LLaVA caption可答性的证明。

特别说明：Video-MMMU的Case Study Analysis 141题与Problem-solving Adaptation159题已核对为全部含非空查询图片；OCR/ASR直接暂缓。Problem-solving Comprehension129题主要需要改参数求解/符号图结构，首版保守整类暂缓；不是宣称全部题永远不可做。Concept Comprehension仅选10个文本候选作题型参考，仍可能依赖课程画面/解说，未做视觉验证。

## 全部分类明细

条件保留表示能力可参考，具体题目仍需视频/caption验证；静态候选数不是高质量数据可产数量。

|管线|数据集|子类|状态|源题数|静态候选|入表|缺口|理由|
|---|---|---|---|---:|---:|---:|---:|---|
| general | Video-MME | Action Reasoning | conditional | 285 | 221 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Action Recognition | conditional | 313 | 283 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Attribute Perception | conditional | 222 | 186 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Counting Problem | deferred | 268 | 0 | 0 | 0 | 精确计数，需计数专项 |
| general | Video-MME | Information Synopsis | conditional | 323 | 275 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | OCR Problems | deferred | 139 | 0 | 0 | 0 | 文字精读，需OCR专项 |
| general | Video-MME | Object Reasoning | conditional | 454 | 370 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Object Recognition | conditional | 354 | 290 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Spatial Perception | conditional | 54 | 47 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Spatial Reasoning | conditional | 56 | 50 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Temporal Perception | conditional | 55 | 32 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME | Temporal Reasoning | conditional | 177 | 143 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Audio-Guided Visual Description | deferred | 110 | 0 | 0 | 0 | 依赖音频引导；当前纯视觉不消费音轨 |
| general | Video-MME-v2 | Basic Counting | deferred | 146 | 0 | 0 | 0 | 精确计数；需对象检测/跟踪与计数专项 |
| general | Video-MME-v2 | Causal Reasoning | conditional | 150 | 125 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Collective Dynamics Analysis | conditional | 74 | 40 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Counterfactual Reasoning | conditional | 48 | 26 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Counterintuitive Comprehension | conditional | 82 | 74 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Cross-Modal Semantic Consistency | deferred | 95 | 0 | 0 | 0 | 要求音画语义对齐 |
| general | Video-MME-v2 | Dyadic Interaction Dynamics | conditional | 88 | 51 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Entity Attribute Change Detection | conditional | 125 | 113 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Entity Existence Change Detection | conditional | 62 | 7 | 7 | 3 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Entity Persistence Tracking | deferred | 73 | 0 | 0 | 0 | 遮挡/换位下持续身份跟踪；需跟踪专项 |
| general | Video-MME-v2 | Event Sequence Ordering | conditional | 151 | 126 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Fine-Grained Action Recognition | deferred | 68 | 0 | 0 | 0 | 精细手脚姿态/短暂运动；当前caption不保证保真 |
| general | Video-MME-v2 | Future Event Prediction | conditional | 32 | 22 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | General Skills Acquisition | conditional | 137 | 95 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | High-Order Narrative Deconstruction | conditional | 63 | 52 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Individual Social Cognition | conditional | 107 | 54 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Motion Properties Analysis | conditional | 65 | 57 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Motion Trajectory Estimation | deferred | 58 | 0 | 0 | 0 | 精确轨迹与方向细节；需轨迹专项 |
| general | Video-MME-v2 | Narrative Cloze Inference | conditional | 50 | 35 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Narrative Turning Point Detection | conditional | 69 | 57 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Numerical Calculation | deferred | 106 | 0 | 0 | 0 | 数值/公式读取与计算；需结构化数理专项 |
| general | Video-MME-v2 | Object Appearance Ordering | conditional | 124 | 102 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Professional Knowledge Acquisition | conditional | 145 | 45 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Repetitive Action Counting | deferred | 49 | 0 | 0 | 0 | 重复动作次数；需密集时序计数专项 |
| general | Video-MME-v2 | Scene Transformation Detection | conditional | 55 | 52 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Spatial Understanding | conditional | 95 | 71 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Symbolic/Metaphorical Interpretation | conditional | 67 | 60 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Temporal Action Localization | deferred | 42 | 0 | 0 | 0 | 精确动作起止；需细粒度grounding专项 |
| general | Video-MME-v2 | Temporal Periodicity Detection | deferred | 68 | 0 | 0 | 0 | 周期/重复间隔；需密集时序专项 |
| general | Video-MME-v2 | Vision-Guided Audio Description | deferred | 135 | 0 | 0 | 0 | 答案依赖音频内容 |
| general | Video-MME-v2 | Visual Recognition | conditional | 323 | 228 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| general | Video-MME-v2 | Visual-Audio Collaborative Reasoning | deferred | 138 | 0 | 0 | 0 | 要求音画联合推理 |
| knowledge | MMVU | Art | conditional | 27 | 25 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Astronomy | conditional | 16 | 15 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Basic Medicine | conditional | 37 | 33 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Biology | conditional | 23 | 23 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Biomedical Engineering | conditional | 61 | 60 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Chemistry | conditional | 24 | 20 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Civil Engineering | conditional | 40 | 40 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Clinical Medicine | conditional | 66 | 59 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Computer Science | conditional | 88 | 64 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Dentistry | conditional | 20 | 18 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Economics | conditional | 34 | 29 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Electrical Engineering | conditional | 46 | 40 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Electromagnetism | conditional | 60 | 55 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Electronics and Communication | conditional | 54 | 36 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Geography | conditional | 25 | 24 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | History | conditional | 10 | 7 | 7 | 3 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Law | conditional | 22 | 18 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Literature | conditional | 26 | 18 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Management | conditional | 22 | 22 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Materials Science | conditional | 22 | 20 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Mechanical Engineering | conditional | 59 | 55 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Mechanics | conditional | 44 | 38 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Modern Physics | conditional | 34 | 24 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Neurobiology | conditional | 44 | 38 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Pharmacy | conditional | 47 | 42 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Preventive Medicine | conditional | 23 | 21 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | MMVU | Thermodynamics | conditional | 26 | 24 | 10 | 0 | 学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖 |
| knowledge | Video-MMMU | ASR | deferred | 23 | 0 | 0 | 0 | 分别依赖精确读字/音频转写 |
| knowledge | Video-MMMU | Case Study Analysis | deferred | 141 | 0 | 0 | 0 | 本地该类全部含额外查询图片；当前MP4-only输入不覆盖 |
| knowledge | Video-MMMU | Concept Comprehension | conditional | 171 | 10 | 10 | 0 | 仅定性概念/解题原理；剔除对白、精确公式/数值读取及计算题 |
| knowledge | Video-MMMU | OCR | deferred | 277 | 0 | 0 | 0 | 分别依赖精确读字/音频转写 |
| knowledge | Video-MMMU | Problem-solving Adaptation | deferred | 159 | 0 | 0 | 0 | 本地该类全部含额外查询图片；当前MP4-only输入不覆盖 |
| knowledge | Video-MMMU | Problem-solving Comprehension | deferred | 129 | 0 | 0 | 0 | 本地主要是改参数重算/公式/图结构解题；当前通用caption不保证必要结构，首版暂缓 |
| long | LVBench | entity recognition | conditional | 677 | 496 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | LVBench | event understanding | conditional | 647 | 483 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | LVBench | key information retrieval | conditional | 291 | 129 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | LVBench | reasoning | conditional | 201 | 158 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | LVBench | summarization | conditional | 58 | 42 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | LVBench | temporal grounding | conditional | 220 | 154 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Action Reasoning | conditional | 180 | 140 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Action Recognition | conditional | 63 | 58 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Attribute Perception | conditional | 27 | 23 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Counting Problem | deferred | 48 | 0 | 0 | 0 | 精确计数，需计数专项 |
| long | Video-MME-long | Information Synopsis | conditional | 163 | 130 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | OCR Problems | deferred | 14 | 0 | 0 | 0 | 文字精读，需OCR专项 |
| long | Video-MME-long | Object Reasoning | conditional | 240 | 183 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Object Recognition | conditional | 54 | 40 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Spatial Perception | conditional | 3 | 1 | 1 | 9 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Spatial Reasoning | conditional | 11 | 8 | 8 | 2 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Temporal Perception | conditional | 6 | 3 | 3 | 7 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
| long | Video-MME-long | Temporal Reasoning | conditional | 91 | 67 | 10 | 0 | caption明确记录所有必要观察才能使用；本轮仅文本静态筛选 |
