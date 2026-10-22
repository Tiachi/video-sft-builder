# 九个视频 Benchmark：下载盘点与任务题数研究

更新：2026-10-22。范围：原始评测数据下载、官方任务分类与题数统计；不修改 QA 构造管道，不调用模型 API，不把评测题并入训练数据。

## 1. 当前完成边界

- **本地已核验**：实际下载并解析 Video-MME、Video-MME v2、LVBench、MotionBench、MMVU、MVBench 的发布标注，以及 MLVU 官方 GitHub 的 9 个 dev 标注文件、test 选择题答案文件。
- **论文／官方材料已核对**：LongVideoBench 的 17 类全量题数；Video-MMMU 的 6 类题数。两者未在本机取得当前受访问控制的完整标注，不能称为逐条重算。
- **服务器当前未核验／未执行下载**：UU 映射、原服务器直连、既有 unimoe 入口均未成功建立 SSH。服务器存在性依据来自 `Tiachi/Unimoe2d5_inference` main 的 `6f840b71b4cb0f9e151a44031fab1848ac1c4673` 文档／配置记录，不代表本次服务器实查。
- 用户确认服务器已登录 HF；具体仓库授权和 NTU 视频是否已有仍待脚本检查。所有服务器下载默认直连，不使用个人 Clash；不会自动绕过访问控制。

完整聚合数值见 [JSON](benchmark_task_counts_2026-10-22.json) 和 [CSV](benchmark_task_counts_2026-10-22.csv)。JSON 的 `annotation_sources` 记录实际读取标注的仓库 revision、文件名、字节数与 SHA256；不保存题目正文。

## 2. 总览：先区分 task、学科与视频领域

“task”表示模型需要完成的能力；“subject/domain”表示视频或知识内容。两种分类轴不能相加成为一个 task 总数。下表的数量均说明统计对象。

| Benchmark | 官方任务／分类结构 | 题数和划分 | 本次计数依据 |
|---|---|---:|---|
| Video-MME | 12 类能力；另有 6 领域、30 视频子类 | test 2,700；900 视频 | 发布 Parquet 实算 |
| Video-MME v2 | 3 个认知层级、10 中类、33 细类 | test 3,200；800 视频 | 发布 Parquet 实算 |
| LVBench | 6 类能力，多标签 | 1,549；103 视频 | 官方 JSONL 展开 `qa` 实算 |
| Video-MMMU | 3 认知轨道、6 能力子类；另有 6 学科大类、30 科目 | 900；3 轨道各 300；300 视频 | 官方论文＋项目 Figure 3 |
| LongVideoBench | 2 层、17 细类 | val 1,337＋test 5,341＝6,678；论文共 3,763 视频 | 官方论文 Table 2；val/test 当前标注待服务器重算 |
| MLVU | dev 9 任务；更新后的 test 11 任务 | dev 2,593；当前 test MCQ 答案 502 条，生成题当前数量待核验 | 官方 dev JSON、test MCQ GT 实算；旧论文单独列出 |
| MVBench | 20 时间理解任务 | 每类 200，共 4,000 | 官方 20 个 JSON 实算 |
| MMVU | 4 学科大类、27 科目；2 题型，不等于 27 能力 task | 官方全量 3,000；公开 val 1,000、583 视频 | 官方 validation JSON 实算；隐藏 test 不可公开下载 |
| MotionBench | 6 运动理解任务 | 公开 8,052 QA：4,018 有答案、4,034 `NA`；5,385 个视频 | 官方 JSONL 与仓库媒体清单实算 |

## 3. 服务器已有资产与补下载范围

以下均为已有仓库记录，当前没有把它们误标成“本次下载成功”。脚本只对配置中的明确路径做检查，不递归扫描 `/mnt/sfs`。

| Benchmark | 已记录标注位置 | 已记录媒体位置 | 当前补齐策略 |
|---|---|---|---|
| Video-MME | `/mnt/sfs/ltj/data/eval/Video-MME/videomme.jsonl` | `/mnt/sfs/ltj/data/eval/Video-MME/data` | 标注导出保留；按全部 900 个 ID 查存在性，完整才跳过视频压缩包 |
| Video-MME v2 | 未找到既有完成记录 | 待检查精确目录 | 官方标注、40 个视频 zip、字幕 zip |
| LVBench | `/mnt/sfs/ltj/data/eval/LVBench/data/train-00000-of-00001.parquet` | `/mnt/sfs/ltj/data/hf_cache/lvbench`，或其 `videos` 子目录 | 先复用 103 个 ID；仅缺失时按官方 YouTube ID 获取，不承诺失效链接必可恢复 |
| Video-MMMU | `/mnt/sfs/ltj/data/eval/VideoMMMU/{Adaptation,Comprehension,Perception}/test-00000-of-00001.parquet` | `/mnt/sfs/ltj/data/eval/VideoMMMU` | 三轨道标注、6 学科 zip、question-only 视频资源；不漏标注内查询图片 |
| LongVideoBench | `/mnt/sfs/ltj/data/eval/LongVideoBench/validation-00000-of-00001.parquet` | `/mnt/sfs/ltj/data/eval/LongVideoBench/videos` | 旧 val 记录不能充当全量；补 val/test、字幕及缺失全量视频归档 |
| MLVU | `/mnt/sfs/ltj/data/eval/MLVU_dev/mlvu/test-00000-of-00001.parquet` | `/mnt/sfs/ltj/data/hf_cache/mlvu` | 补齐 dev 的 OE 标注、缺失视频与 test；不假设旧 MCQ 适配器已含全部 9 任务 |
| MVBench | 未找到既有完成记录 | 检查 `/mnt/sfs/ltj/data/eval/MVBench` 和 `hf_cache/mvbench` | 20 JSON、公开视频归档、NTU 320 文件清单；缺 NTU 明确报 blocker |
| MMVU | 未找到既有完成记录 | 检查 `/mnt/sfs/ltj/data/eval/MMVU` 和 `hf_cache/mmvu` | 官方公开 validation 标注及视频；隐藏 test 不伪造“已下载” |
| MotionBench | `/mnt/sfs/ltj/data/eval/MotionBench/MotionBench/video_info.meta.jsonl` | 同目录下 `public-dataset` 与 `self-collected` | 当前官方媒体 5,385；旧 2,706 是历史评测资产数，按官方文件路径、size 复用后补缺；不下载 Caption-train |

LongVideoBench：论文 val 记 752 视频；旧服务器报告记 753 个引用视频。这里分别保留，后续以当前标注路径去重和文件核验解释差异，不擅自改成同一个数。

## 4. Video-MME：12 个能力任务

统计：`videomme/test-00000-of-00001.parquet`，按 `task_type`，总和 2,700。[官方项目](https://github.com/MME-Benchmarks/Video-MME)，[发布数据](https://huggingface.co/datasets/lmms-eval/Video-MME)。

| 官方类别 | 中文说明 | 题目数 |
|---|---|---|
| Action Reasoning | 动作推理 | 285 |
| Action Recognition | 动作识别 | 313 |
| Attribute Perception | 属性感知 | 222 |
| Counting Problem | 计数 | 268 |
| Information Synopsis | 信息概括 | 323 |
| OCR Problems | 文字识别 | 139 |
| Object Reasoning | 对象推理 | 454 |
| Object Recognition | 对象识别 | 354 |
| Spatial Perception | 空间感知 | 54 |
| Spatial Reasoning | 空间推理 | 56 |
| Temporal Perception | 时间感知 | 55 |
| Temporal Reasoning | 时间推理 | 177 |


领域分布（题数，单独统计轴）：

| 官方类别 | 中文说明 | 题目数 |
|---|---|---|
| Artistic Performance | — | 360 |
| Film & Television | — | 360 |
| Knowledge | — | 810 |
| Life Record | — | 630 |
| Multilingual | — | 90 |
| Sports Competition | — | 450 |


30 个视频子类均为 **90 题／类**，不是 30 个能力 task：

| 视频子类 | 题数 |
|---|---|
| Acrobatics | 90 |
| Animation | 90 |
| Astronomy | 90 |
| Athletics | 90 |
| Basketball | 90 |
| Biology & Medicine | 90 |
| Daily Life | 90 |
| Documentary | 90 |
| Esports | 90 |
| Exercise | 90 |
| Fashion | 90 |
| Finance & Commerce | 90 |
| Food | 90 |
| Football | 90 |
| Geography | 90 |
| Handicraft | 90 |
| Humanity & History | 90 |
| Law | 90 |
| Life Tip | 90 |
| Literature & Art | 90 |
| Magic Show | 90 |
| Movie & TV Show | 90 |
| Multilingual | 90 |
| News Report | 90 |
| Other Sports | 90 |
| Pet & Animal | 90 |
| Stage Play | 90 |
| Technology | 90 |
| Travel | 90 |
| Variety Show | 90 |


## 5. Video-MME v2：三级分类与题数组

统计：官方 `test.parquet` **每行一题**，不是每行一个四题组；总共 3,200 行、800 视频。`group_type` 的 logic/relevance 为组结构标签，不是能力类别；logic 1,124 题、relevance 2,076 题。[官方代码](https://github.com/MME-Benchmarks/Video-MME-v2)，[当前数据](https://huggingface.co/datasets/MME-Benchmarks/Video-MME-v2)。

一级层级：Level 1（时间信息聚合）1,053；Level 2（动态理解）1,049；Level 3（复杂时序推理）1,098。

下表按原始 `level / second_head / third_head` 三元组分组；同名细类如跨层出现也不合并。原始数据共有 10 个 `second_head`、33 个 `third_head`。

| Level | 中类 | 细类 | 题数 |
|---|---|---|---|
| 1 | Frame-Only | Basic Counting | 146 |
| 1 | Frame-Only | Numerical Calculation | 106 |
| 1 | Frame-Only | Visual Recognition | 323 |
| 1 | Frames & Audio | Audio-Guided Visual Description | 110 |
| 1 | Frames & Audio | Cross-Modal Semantic Consistency | 95 |
| 1 | Frames & Audio | Vision-Guided Audio Description | 135 |
| 1 | Frames & Audio | Visual-Audio Collaborative Reasoning | 138 |
| 2 | Action & Motion | Fine-Grained Action Recognition | 68 |
| 2 | Action & Motion | Motion Properties Analysis | 65 |
| 2 | Action & Motion | Motion Trajectory Estimation | 58 |
| 2 | Action & Motion | Repetitive Action Counting | 49 |
| 2 | Action & Motion | Temporal Action Localization | 42 |
| 2 | Change | Entity Attribute Change Detection | 125 |
| 2 | Change | Entity Existence Change Detection | 62 |
| 2 | Change | Scene Transformation Detection | 55 |
| 2 | Order | Event Sequence Ordering | 151 |
| 2 | Order | Object Appearance Ordering | 124 |
| 2 | Order | Temporal Periodicity Detection | 68 |
| 2 | Temporal Reasoning | Causal Reasoning | 150 |
| 2 | Temporal Reasoning | Future Event Prediction | 32 |
| 3 | Complex Plot Comprehension | High-Order Narrative Deconstruction | 63 |
| 3 | Complex Plot Comprehension | Narrative Cloze Inference | 50 |
| 3 | Complex Plot Comprehension | Narrative Turning Point Detection | 69 |
| 3 | Complex Plot Comprehension | Symbolic/Metaphorical Interpretation | 67 |
| 3 | Physical World Reasoning | Counterfactual Reasoning | 48 |
| 3 | Physical World Reasoning | Counterintuitive Comprehension | 82 |
| 3 | Physical World Reasoning | Entity Persistence Tracking | 73 |
| 3 | Physical World Reasoning | Spatial Understanding | 95 |
| 3 | Social Behavior Analysis | Collective Dynamics Analysis | 74 |
| 3 | Social Behavior Analysis | Dyadic Interaction Dynamics | 88 |
| 3 | Social Behavior Analysis | Individual Social Cognition | 107 |
| 3 | Video-Based Knowledge Acquisition | General Skills Acquisition | 137 |
| 3 | Video-Based Knowledge Acquisition | Professional Knowledge Acquisition | 145 |


中类合计：

| 中类 | 题数 |
|---|---|
| Action & Motion | 282 |
| Change | 242 |
| Complex Plot Comprehension | 249 |
| Frame-Only | 575 |
| Frames & Audio | 478 |
| Order | 343 |
| Physical World Reasoning | 298 |
| Social Behavior Analysis | 269 |
| Temporal Reasoning | 182 |
| Video-Based Knowledge Acquisition | 282 |


## 6. LVBench：6 个能力，多标签

统计：官方 `video_info.meta.jsonl` 的 103 条视频记录展开得到 1,549 QA，`qa[].question_type` 为列表。[官方代码](https://github.com/zai-org/LVBench)，[官方标注](https://huggingface.co/datasets/zai-org/LVBench)。

| 官方类别 | 中文说明 | 题目数 |
|---|---|---|
| key information retrieval | 关键信息检索 | 291 |
| event understanding | 事件理解 | 647 |
| summarization | 总结 | 58 |
| entity recognition | 实体识别 | 677 |
| reasoning | 推理 | 201 |
| temporal grounding | 时间定位 | 220 |


类别标记总计 **2,094**，不是新增题目：1,038 题含 1 个标签、477 题含 2 个标签、34 题含 3 个标签。

视频内容类别对应的题数：cartoon 283、documentary 197、live 262、selfmedia 317、sport 240、tv 250；这个轴总和 1,549。

## 7. Video-MMMU：3 轨道、6 子类

[官方论文](https://arxiv.org/html/2501.13826)和[官方 Figure 3](https://videommmu.github.io/assets/figures/figure3_0308.png)给出以下 6 类精确题数；本机未读取 gated Parquet，因此标记为官方图表证据。3 轨道各 300 题，合计 900。

| 认知轨道 | 子类 | 中文含义 | 题数 |
|---|---|---|---|
| Perception | OCR | 文字／图表／公式信息感知 | 277 |
| Perception | ASR | 语音内容识别 | 23 |
| Comprehension | Concept Comprehension | 概念理解 | 171 |
| Comprehension | Problem-solving Strategy Comprehension | 解题策略理解 | 129 |
| Adaptation | Case Study Analysis | 新案例分析 | 141 |
| Adaptation | Problem-solving Strategy Adaptation | 新问题中的策略迁移 | 159 |


另一分类轴是 Art、Business、Science、Medicine、Humanities、Engineering 共 6 学科大类、30 科目。图中比例为四舍五入值，不反推科目题数。每科目精确题数待服务器当前 Parquet 重算。

题型不能统一视作普通四选一：存在 OE，概念理解还含多陈述组合判断；部分迁移题有额外查询图片。下载保留原始标注与图片字段，不直接转换成当前 SFT 的单选协议。[代码](https://github.com/EvolvingLMMs-Lab/VideoMMMU)，[数据](https://huggingface.co/datasets/lmms-eval/VideoMMMU)。

## 8. LongVideoBench：17 细类

全量 6,678 QA 的分类数直接取[官方论文 Table 2](https://arxiv.org/html/2407.15754#S1.T2)。**这里是 val＋test 全量，不是 val 1,337 的细分数**。L1 是单时刻感知，L2 是跨时刻关系；与本项目 caption 的 L1/L2 命名无对应关系。

| 层级 | 代码 | 官方 task | 中文说明 | 题数 |
|---|---|---|---|---|
| L1 | S2E | Scene-referred Event | 场景指代的事件 | 410 |
| L1 | S2O | Scene-referred Object Existence | 场景指代的对象存在 | 403 |
| L1 | S2A | Scene-referred Object Attribute | 场景指代的对象属性 | 403 |
| L1 | E2O | Event-referred Object | 事件指代的对象 | 393 |
| L1 | O2E | Object-referred Event | 对象指代的事件 | 401 |
| L1 | T2E | Text-referred Event | 字幕指代的事件 | 398 |
| L1 | T2O | Text-referred Object Existence | 字幕指代的对象存在 | 387 |
| L1 | T2A | Text-referred Object Attribute | 字幕指代的对象属性 | 402 |
| L2 | E3E | Event before/after Event | 事件之间的先后关系 | 406 |
| L2 | O3O | Object before/after Object | 对象出现的先后关系 | 394 |
| L2 | SSS | Sequence of Scenes | 多场景排序 | 398 |
| L2 | SOS | Scene-referred Object Tracking | 场景指代的对象追踪 | 381 |
| L2 | SAA | Scene-referred Object Attribute Change | 跨场景对象属性变化 | 375 |
| L2 | T3E | Event before/after Text | 字幕前后的事件 | 401 |
| L2 | T3O | Object before/after Text | 字幕前后的对象 | 391 |
| L2 | TOS | Text-referred Object Tracking | 字幕与对象追踪 | 380 |
| L2 | TAA | Text-referred Object Attribute Change | 跨字幕对象属性变化 | 348 |


**源表自身存在 7 题差额**：表中写 L1 合计 3,204，但其 8 类逐行相加为 3,197；L2 的 9 类相加为 3,474。因此上表逐类和为 **6,671**，与官方总数 6,678 不一致。已同时核对 [NeurIPS 正式出版 PDF 第 3 页 Table 2](https://proceedings.neurips.cc/paper_files/paper/2024/file/329ad516cf7a6ac306f29882e9c77558-Paper-Datasets_and_Benchmarks_Track.pdf#page=3)，相同数字出现在正式版，不只是 HTML 转换。本表逐项保留论文原值，不猜测把 7 题补进某一类；最终以当前发布标注重算修正。发布文件 `lvb_val.json` 有答案，`lvb_test_wo_gt.json` 是无公开 GT 的测试题；下载后可统计题类，不能把测试题当作本地有答案评分集。[代码](https://github.com/longvideobench/LongVideoBench)，[官方数据](https://huggingface.co/datasets/longvideobench/LongVideoBench)。

## 9. MLVU：必须按 dev／更新后的 test 区分

dev 从[官方 GitHub data](https://github.com/JUNJIE99/MLVU/tree/bc1a68d1efbcdb949a20a83677e1e8b4ec9f3e79/data)逐文件计数，9 任务合计 **2,593**，其中 **2,175 MCQ＋418 OE**。此前若把 2,593 叫“7 类 MCQ 总数”则不正确。

当前 test MCQ 从[官方 `test_res.json`](https://github.com/JUNJIE99/MLVU/blob/bc1a68d1efbcdb949a20a83677e1e8b4ec9f3e79/evaluation_test/test_res.json)按 `question_type` 计数，9 类合计 **502**。它只覆盖选择题答案，不是 11 任务的完整题目文件。

| 任务组 | 官方任务 | 中文 | 题型 | dev 实算 | 当前 test MCQ GT 实算 |
|---|---|---|---|---|---|
| 整体 | Topic Reasoning | 主题推理 | MCQ | 264 | 91 |
| 整体 | Anomaly Recognition | 异常识别 | MCQ | 200 | 39 |
| 整体 | Video Summarization | 视频总结 | OE | 217 | 该 GT 文件不包含 |
| 单细节 | Needle QA | 长视频检索式问答 | MCQ | 355 | 60 |
| 单细节 | Ego Reasoning | 第一视角推理 | MCQ | 352 | 53 |
| 单细节 | Plot QA | 剧情问答 | MCQ | 539 | 50 |
| 单细节 | Sub-Scene Captioning | 子场景描述 | OE | 201 | 该 GT 文件不包含 |
| 多细节 | Action Order | 动作顺序 | MCQ | 259 | 70 |
| 多细节 | Action Count | 动作次数 | MCQ | 206 | 60 |
| 单细节 | Sports QA | 体育问答 | MCQ | 不适用 | 36 |
| 多细节 | Tutorial QA | 教程问答 | MCQ | 不适用 | 43 |


旧[论文附录 E](https://arxiv.org/html/2406.04264#A5)给出的原始 9 任务 test 是 **509**：其中 VS 40、SSC 46，其余 7 类 MCQ 423。后续发布加入 Sports QA 36、Tutorial QA 43，所以不能继续把当前 11 任务 test 写成 509。**不能仅把旧 OE 的 86 条与当前 MCQ 502 条相加，宣称已经实际核验当前 test 共 588 条**；需要读取最新 `test_generation_tasks.json`／生成题 GT 再确认。

当前官方 test 数据有 `test-ground-truth/test_mcq_gt.json`、`test_ssc_gt.json`、`test_vs_gt.json`；较新的官方 GitHub 已宣布 test GT 发布，HF README 内旧“GT 未公开”新闻不能覆盖此更新。[dev 数据](https://huggingface.co/datasets/MLVU/MVLU)，[test 数据](https://huggingface.co/datasets/MLVU/MLVU_Test)。

## 10. MVBench：20 任务，每类 200 题

统计：[官方 HF `json/`](https://huggingface.co/datasets/OpenGVLab/MVBench/tree/main/json)20 个列表文件。各 200，合计 4,000。任务具有原始区间、字幕或帧目录等不同输入协议，不能一律当作完整 MP4。官方 [MVBENCH.md](https://github.com/OpenGVLab/Ask-Anything/blob/main/video_chat2/MVBENCH.md)介绍来源与自动构题方法。

| 官方类别 | 中文说明 | 题目数 |
|---|---|---|
| action_antonym | 动作反义辨别 | 200 |
| action_count | 动作计数 | 200 |
| action_localization | 动作时间定位 | 200 |
| action_prediction | 下一动作预测 | 200 |
| action_sequence | 动作顺序 | 200 |
| character_order | 字符书写顺序 | 200 |
| counterfactual_inference | 反事实推理 | 200 |
| egocentric_navigation | 第一视角导航 | 200 |
| episodic_reasoning | 情节推理 | 200 |
| fine_grained_action | 细粒度动作 | 200 |
| fine_grained_pose | 细粒度姿态 | 200 |
| moving_attribute | 运动对象属性 | 200 |
| moving_count | 运动对象计数 | 200 |
| moving_direction | 运动方向 | 200 |
| object_existence | 对象存在 | 200 |
| object_interaction | 对象交互 | 200 |
| object_shuffle | 遮挡后的对象追踪 | 200 |
| scene_transition | 场景变化 | 200 |
| state_change | 状态变化 | 200 |
| unexpected_action | 异常动作 | 200 |


官方媒体包当前不含需原站获取的 **320 个 NTU RGB+D 视频**。检查依据是官方 `video/MVBench_videos_ntu.txt`，不能仅因 HF 全部 zip 下载结束就声称 MVBench 媒体全量完整。脚本保留缺失数和 blocker，不自行同意原站条款。

## 11. MMVU：27 科目与 2 种题型

这里指 [yale-nlp/MMVU](https://github.com/yale-nlp/MMVU)，避免与同名的其他图像数据集混淆。官方整体是 3,000 题／1,529 视频／4 学科大类／27 科目；**当前公开 `validation.json` 为 1,000 题、583 个视频**。隐藏 test 无法按公开仓库补全，不写成缺失可下载包。

以下为公开 validation 按 `metadata.subject` 实算；科目标签不是独立能力 task。四学科大类是 Science、Healthcare、Humanities & Social Sciences、Engineering，当前 JSON 不显式提供大类字段，因此不凭主观映射加总。

| 科目 | 公开 val 题数 |
|---|---|
| Art | 27 |
| Astronomy | 16 |
| Basic Medicine | 37 |
| Biology | 23 |
| Biomedical Engineering | 61 |
| Chemistry | 24 |
| Civil Engineering | 40 |
| Clinical Medicine | 66 |
| Computer Science | 88 |
| Dentistry | 20 |
| Economics | 34 |
| Electrical Engineering | 46 |
| Electromagnetism | 60 |
| Electronics and Communication | 54 |
| Geography | 25 |
| History | 10 |
| Law | 22 |
| Literature | 26 |
| Management | 22 |
| Materials Science | 22 |
| Mechanical Engineering | 59 |
| Mechanics | 44 |
| Modern Physics | 34 |
| Neurobiology | 44 |
| Pharmacy | 47 |
| Preventive Medicine | 23 |
| Thermodynamics | 26 |


| 题型 | 公开 val 题数 |
|---|---|
| multiple-choice | 625 |
| open-ended | 375 |


官方[数据](https://huggingface.co/datasets/yale-nlp/MMVU)保留专家 rationale／knowledge 信息；本轮只下载和统计，不把它直接当成本项目待决定的 CoT 方案。

## 12. MotionBench：6 类，区分全题与公开答案

统计：[官方评测 JSONL](https://huggingface.co/datasets/zai-org/MotionBench/blob/main/MotionBench/video_info.meta.jsonl)，8,052 行展开后仍为 8,052 QA；官方 `MotionBench/` 下 5,385 个 MP4，与标注不同视频路径数一致。排除独立的 `MotionBenchCaption-train/`，避免把训练 caption 也当 benchmark 下载。

| 官方 task | 中文 | 全部公开题 | 有公开答案 | 答案为 NA |
|---|---|---|---|---|
| Action Order | 动作顺序 | 1001 | 519 | 482 |
| Camera Motion | 相机运动 | 775 | 385 | 390 |
| Location-related Motion | 位置相关运动 | 1143 | 546 | 597 |
| Motion Recognition | 运动识别 | 2944 | 1478 | 1466 |
| Motion-related Objects | 运动相关对象 | 1415 | 690 | 725 |
| Repetition Count | 重复次数 | 774 | 400 | 374 |


合计：8,052／4,018／4,034。`NA` 表示没有公开正确答案，不能解释为坏题、拒绝题或从总题量中静默删除；4,018 是本地可按公开 GT 评分的题数。

## 13. 执行与产物

服务器上运行（已知的 SFT 项目 checkout；不调用任何模型）：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
bash scripts/git/sync_pull_ff_only.sh
bash scripts/benchmarks/run.sh download
```

仅做已有资产与标注统计、不下载数据集：

```bash
bash scripts/benchmarks/run.sh inventory
```

首次运行自动在下面的专用 venv 安装工具依赖；即使 inventory 首次也可能下载工具包，但不下载 benchmark。默认直连清华 PyPI，个人代理变量只在子进程内取消，父终端和系统网络配置不变。

所有新增产物位于 `/mnt/sfs/ltj/data/benchmark_research_20261022/`：

```text
_tools/venv/                           # 独立工具依赖，不改训练环境
snapshots/<benchmark>/<revision>/      # 官方原始标注、视频或压缩包
reports/<UTC时间>/report.json          # 当前逐项下载／已有数据／分类统计状态
latest_report.json                    # 最新报告路径及完整性状态
```

`configs/benchmark_assets.json` 是版本固定的来源和已有路径登记，MLVU dev/test 分两项，所以 9 个 benchmark 对应 10 个下载单元。版本固定后不悄悄跟随 main 更新。

实现边界：

1. 公有文件可匿名使用非个人代理的 HF mirror；**HF Token 只发送到官方 huggingface.co**。gated 仓库必须有对应授权和官方站连通性；失败明确 blocked，不把 Token 自动交给第三方镜像，不自动更换数据集来源。
2. 单文件／注册媒体引用检查，无全盘递归扫描。已有媒体按精确相对路径＋size 复用；视频压缩包仅在完整标注的全部预期视频引用都存在且非零时跳过。这里是存在性／大小核验，**不等于解码／内容校验**。
3. 旧原片与旧标注不写入、不移动；不同版本写独立 snapshot。HF 缓存支持下载断点，重跑同一命令继续；并发启动由文件锁拒绝。已有 snapshot 文件大小不匹配则保留并 blocked。
4. 视频压缩包下载完毕保留原始归档，**当前脚本不自动解压多段 tar 或 zip**。报告分别标记 `download_status`、`archive_extraction=not_performed` 和 `media_decode_verification=not_performed`；不能将“包下载完”称为“可直接跑评测”。已有解压媒体继续在原路径复用，索引记录其来源。
5. 报告按标注文件分项列出，不将同一数据的 JSON、Parquet 两种表示相加；混合媒体、baseline 辅助资源、hidden test 的可达状态单列。任何仓库失败继续处理其他仓库，最后整体非零并给出报告，保留已完成内容。
6. 首版下载器不承诺自动补齐 gated 授权、失效 YouTube、NTU 原站访问，也不声称只检查文件存在就完成高质量媒体校验。服务器回传报告后，才能确认下载缺口和安排归档解包／剩余受限资源处理。

验证状态：新增 9 项离线边界测试通过，覆盖多标签、NA 口径、完整／子集媒体复用、零字节文件、路径越界、精确 size 复用和镜像不接收 HF Token。全项目 174 项测试通过（2 项 FFmpeg 媒体测试因环境条件跳过），Bash 语法检查通过。服务器真实网络、授权、容量及全量下载仍未运行验证。

## 14. 当前待完成项

- 运行上述下载命令，取得真实 `report.json`；当前没有服务器下载完成证据。
- 从服务器已授权的 Video-MMMU 标注重算科目和题型细分；从 LongVideoBench 当前 val/test 标注重算分割细分，核对论文与当前发布版差异。
- 读取 MLVU 当前 test 生成题文件，确认 2 类 OE 的实际条数，再填完整 11 任务 test 表；当前不会用旧论文条数冒充最新文件实算。
- 若 NTU 清单有缺失，用户需在原数据方账号权限下取得文件；若 HF 访问受限，依据报告区分缺授权与网络不通。
- 下载包完成后再做安全解包和媒体覆盖／解码核验；本轮不提前声称这些步骤已完成。
