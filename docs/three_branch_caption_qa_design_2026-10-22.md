# General / Long / Knowledge：三级 caption 到 QA 的三管线设计

**后续实现已完成：** 见[三分支能力方案](benchmark_ability_recipe_implementation_2026-10-22.md)。Knowledge已确认2+3并复用A3；新recipe包含32能力task/256模板及Long单段检索。下文“尚未实现/槽位待定/QA_KNOWLEDGE角色”是早先设计状态，已被该实现替代；96分类参考表及其原始证据继续有效。

日期：2026-10-22。依据：用户最新三分支需求、Knowledge 专业知识边界和 Long 单段检索选择；原始标注来自本地已校验的官方版本。本文更新四模块设计，不将参考样例当成已通过视觉审核的训练数据。

## 1. 当前结论及实际状态

共核对 **96 个分类组**：General 的 Video-MME 12 类与 v2 33 类，Long 的 Video-MME long 子集12类与 LVBench 6类，Knowledge 的 Video-MMMU 6类与 MMVU 27学科。每个条件保留类别目标10题；暂缓类别不凑10题；源题不足或筛后不足如实列出。

最终参考表 **726行，695道独立原题**：General307行、Long142行、Knowledge277行；75个分类组条件保留、21组整类暂缓，70组达到每组10题，5组不足。重复行来自用户指定的跨分支重叠参考池和LVBench真实多标签，不用于扩充单类数量。上述是静态参考选样统计，不是高质量训练QA的实际通过数量。

| 内容 | 状态 |
|---|---|
| 三根 QA 管线及来源范围 | 用户已确认的设计 |
| Knowledge 可结合专业知识，但必须依赖视频观察 | 用户已确认，覆盖旧 General 的纯事实约束在该新分支的适用范围 |
| Long 新增长上下文单段检索 | 用户已确认，覆盖旧的“Long 每题都必须多段证据”限制；跨段任务仍必须多段 |
| 原始标注分类、题数、选项与答案归档 | 已通过本地只读脚本提取；版本和输入哈希见导出 manifest |
| 题目适合当前 caption 的判断 | 文本静态筛选及风险分析，**未观看原视频、未检查其三级 caption**；不能称逐题视觉核验 |
| General / Long 当前调度器 | 现有运行代码仍是历史9+3任务注册表、General2+3和Long1+2；新类别没有自动生效 |
| Knowledge 运行分支、提示、角色、槽位和导出 | **尚未实现/配置**；本次只交付设计、参考表和提取工具 |
| 模型调用 / 服务器执行 | 本次0模型调用；没有运行服务器或修改已付费轮次 |

本次不修改 `configs/project.example.json`、运行任务表、模型路由或已有数据；避免把设计变化悄悄带入下一次付费运行。Knowledge 数量、fit/balance拆分、三分支混合比例和具体API预算仍待确定。

## 2. 三根管线的职责

| 分支 | benchmark参考池 | 推荐能力组织 | 能构造的前提 | 数量与调度 |
|---|---|---|---|---|
| General | Video-MME全时长；Video-MME-v2 | 可见实体/动作/空间、变化、事件顺序、定性运动、局部/全局语义、证据充分的因果与叙事关系 | 必要观察在L1/L2/L3明确出现；不能把对白、图表标签或动机臆测补成事实 | 沿用最多2适配+3均衡候选；新能力映射及模板待落地 |
| Long | Video-MME `duration=long`；LVBench | 长上下文单段检索、跨段比较/关联、顺序/时间线、分段/全局总结、粗粒度时间范围理解 | 单段检索需记录检索目标/实际证据段；跨段必须多个不可替代证据；不设生产最低片长 | 沿用最多1适配+2均衡候选；新增检索task待实现 |
| Knowledge | Video-MMMU；MMVU | 现象→概念、观察→机制、操作→原理/用途、可见条件→知识应用、基于已观察事实的案例解释 | 专业知识可作推理规则；对象、现象、动作、条件必须来自视频caption；读字/计算/缺查询图则弃答 | 数量、fit/balance和预算待定，不套用General5或Long3 |

Video-MME全量与long子集有重叠，这是用户指定的参考范围。表格允许同一原题在两分支出现，并保留source_id；**不因此新增用户之前暂不处理的跨分支语义去重流程**。LVBench是多标签，原题可真实属于多个子类，因此表格行数不等于独立原题数。

### 分类不是同一个维度

本轮将用户说的Video-MMMU“6个分类”按标注`qa_type`理解为OCR、ASR、Concept Comprehension、Problem-solving Comprehension、Case Study Analysis、Problem-solving Adaptation六种能力子类；不是论文另列的Art/Business/Science/Medicine/Humanities/Engineering六学科大类。MMVU则按用户明确指定的27学科整理。

`branch`、`ability_task`、`subject`、`benchmark_subclass`须分开：MMVU的Chemistry是学科，不应和因果推理、动作识别放进同一个task小根堆。建议外置映射：

```text
branch → 可用ability_task → 证据适配判定 → 语言/题型/选项数
knowledge另外维护subject覆盖统计
benchmark / source_subclass / source_id → 外置来源与例题索引
```

各分支按归一化能力task做堆调度，语言/题型仍按原全局缺口选择；学科覆盖独立报告，首版不机械要求27学科在任意MP4批次等量。也不将Video-MME12类和v2的33类简单拼成45个互斥task。具体映射白名单需下一步实现前冻结。

## 3. 哪些类别或题目暂缓

完整96行状态/计数表见[分类与抽样统计](three_branch_reference_category_summary_2026-10-22.md)，机器摘要见[聚合JSON](three_branch_reference_category_summary_2026-10-22.json)。Q/A原文在代码仓库外的参考导出目录。

| 待建专项 | 本次主要涉及的原分类/题目 | 当前链路的缺口 |
|---|---|---|
| OCR / 文本与符号结构 | Video-MME OCR；Video-MMMU OCR；其他类别夹杂的姓名、标题、公式、代码、板书/标签题 | 通用caption不保证准确字形、数值、符号和版面关系 |
| 计数 | Video-MME Counting；v2 Basic Counting / Repetitive Action Counting；其他类别的数量变化/自由度等 | 需要稠密观测、对象或事件身份关联，摘要不能保证不漏 |
| 音频 / 音画 | Video-MMMU ASR；v2四个音频/音画任务；对白/歌词/旁白依赖题 | 本项目当前不消费音轨；不能通过视觉caption补对白 |
| 数理结构与求解 | v2 Numerical Calculation；本地Video-MMMU Problem-solving Comprehension大多改参数重算；精确仪表/图表题 | 需要可靠参数、公式、图结构，再校验求解；专业知识本身补不了缺失输入 |
| 细粒度动作/跟踪/轨迹 | v2 Fine-Grained Action Recognition / Entity Persistence Tracking / Motion Trajectory Estimation | 短暂细节和身份连续性可能在采样或caption压缩中丢失；并非这些能力在原理上不能文字表达 |
| 精确时间定位/周期 | v2 Temporal Action Localization / Temporal Periodicity Detection；其他类别的精确起止/时长输出 | 当前L1窗口不是事件真实边界；程序可格式化时间，但不能创造边界 |
| 额外查询图片与迁移 | Video-MMMU Case Study Analysis / Problem-solving Adaptation | 本地两类共300题全部带image字段；仅MP4不包含额外解题图片 |
| 专业细粒度视觉 | 部分MMVU医学影像、微观结构、信号/仪表等题 | 学科可以保留，具体题需专业视觉提取；不能整科删除或整科放行 |

这些是**首版保守工程决策**，不等于对应benchmark质量差，也不等于所有题永远不可由caption表达。若将来专项证据链可无损提取所需细节，可重新放行。

条件保留也不等于无需限制：未来预测、反事实、隐喻、人物心理/群体关系等仅能参考题目结构。若原片缺少充分的可见依据、答案有多个合理解释、依赖未消费对白或未说明规则，必须弃答/拒绝，不能为了任务均衡硬造推理题。若试产显示这类任务无法稳定过A7，应关闭该任务，而不是放宽事实约束。

## 4. 从caption到QA的共同链路

```text
模块2：L1/L2/L3完整 + C_GATE通过
  → 建只读证据索引（caption_id / 原片绝对时间 / 可见对象动作状态 / 不确定性）
  → 分支能力适配（General / Long / Knowledge可并行入选）
  → 槽位调度（先fit后balance；task先于语言/题型）
  → 检索适合的“任务定义 + 例题结构 + 证据要求 + 答题约束”
  → 一次文本生成请求内提出QA与事实/证据引用，允许abstain
  → 本地硬检查 → 每题一次A7原视频+文本综合审核
  → pass全保留；fail/uncertain/error进reject；不补题、不重看、不修答案
```

**例题内容不能成为当前视频事实。** 用参考题启发问法、推理关系和干扰项结构，不可将原benchmark人物、场景、概念答案复制给无关MP4。生产MCQ仍为3/4/6选一；参考表保留原4/5/8/10等选项，不直接裁剪选项，以免破坏原题答案。

模板库建议每个归一化能力拆成：`evidence_requirements / question_intent / answer_contract / distractor_rules / abstain_conditions / reference_ids`。轮转问法只在结构层做；事件排序应由程序随机排列候选事件并重算正确序列/答案。参考题只能辅助生成，不替代task适配、独立选项唯一性和A7审核。

### Knowledge的明确边界

```text
observed_premises：视频caption明确记录的现象、对象、动作、前后变化，带caption_id和时间
domain_rule：用于推理的专业概念/原理；允许模型已有知识，记录规则和不确定性
derived_answer：由上述观察+规则推出；不得新增未观察到的参数或诊断体征
```

这三个部分存外部证据记录，**不是训练CoT，也不新增最终顶层字段**。临床/工程等题的概念正确性仍可能超出审核模型能力，不能把一个VLM的赞同当专家证明。首版先产自动审核候选，人工准确率未知。若模型不能可靠判断专业规则或存在多种合理解释，走uncertain→reject。

Knowledge特别应做视频必要性检查：去掉视频事实后若仍可仅靠题干与常识稳定答出，则不合格。首版把这一检查并入生成/A7已有调用中的明确判据；额外text-only对照模型调用属于未来增强，不自动新增成本。模型自评无法证明必要性，后续若需要量化应安排独立对照评估。

### Long的新增边界

长上下文检索题允许一个关键证据段，但应询问在全片上下文中有辨识度的目标，避免任意短片都能回答的单帧问题仅因原片长而标Long。外置记录`evidence_mode=single_segment_retrieval / multi_segment / global`作为拟定审计维度；不新增随意时长阈值。跨段比较仍要证据不可替代；事件时间线/层级全局总结仍只做OE，检索/跨段QA可OE或MCQ。

## 5. API接入与成本边界

| 位置 | 本次设计中的输入 | 是否新增调用 |
|---|---|---|
| A1/L1 | 当前10s等局部视频视图，实际参数由冻结配置决定 | 不变 |
| A2/L2 | 上次累计文字 + 新L1 + 当前30s等新增块视频 | 不变；不重送累计视频前缀 |
| L3 / C_GATE | 复用末次L2为L3；全片稀疏视图检查一次 | 不变 |
| A3 / General | caption+任务+模板/参考结构+调度槽位 | 当前文本调用方式不变，新参考检索尚未接入 |
| A5 / Long | 同上，增加单段检索适配与任务证据模式 | 设计增加能力，不增加每视频槽位；尚未实现 |
| `QA_KNOWLEDGE`（逻辑名） | caption观察前提+领域任务/学科+规则约束+槽位 | 新分支将增加文本请求；具体角色映射/槽位/预算待定，不命名A4 |
| A7 | 每候选完整原视频+对应文本；Knowledge额外核规则/视频必要性，Long按任务核证据模式 | 每新增Knowledge候选最多新增一次A7；现有General/Long审核次数合同不变 |
| 提取参考样例/统计/模板轮转/程序排序 | 本地标注文本、索引与配置 | 0模型调用 |

三分支共享一次caption与C_GATE，不能按三分支重复生成caption。新增Knowledge的费用必须在预算预检中显式出现；没有Knowledge槽位预算时不允许自动启用该分支。现有两分支8题均送审的旧成本公式，不可当作启用Knowledge后的总成本。

## 6. 最终格式与外置产物

仍保持统一12个顶层字段：`id/source/conversations/task/question_type/media_info/media/modal_mask/quality/cot/language/tokens`，三分支无需三套JSON格式。`source`仍写实际MP4来源，不能写Video-MME/MMVU来冒充新MP4来源。CoT仍为后续独立管线，QA产物`cot=null`。

建议通过既有`task`结构记录分支/归一化能力；新Knowledge pipeline枚举属于后续schema迁移，尚未修改运行schema。学科、benchmark映射、例题引用、观察前提、领域规则、采样/调用/筛除原因、血缘、统计均在训练JSON外。参考导出JSONL只是研究索引，不是12字段训练JSON。

建议派生输出（逻辑路径，不冒充当前运行布局）：

```text
03_synthesis/{general,long,knowledge}_candidates.jsonl
03_synthesis/evidence.jsonl / generation.jsonl / reference_usage.jsonl
04_quality/local_checks.jsonl / audits.jsonl / reject.jsonl
release/<version>/{general,long,knowledge}.jsonl
reports/<run_id>/{branch_task,knowledge_subject,source_stage,stage_source,cost,shortages}.*
```

每个筛除环节记录源数量、条件保留/暂缓/拒绝/blocked和主原因，来源×阶段/阶段×来源双向统计；QA行数、独立原题数、多标签重复和跨分支重复分别统计。参考库的静态筛除与生产A7质量reject是两种流程，不能混计。

## 7. 原始QA参考表在哪里、如何复现

本次本地最终目录：`C:/Users/Tiachi/Documents/Dataset/x_temp/qa_reference_three_branches_20261022_v3`。早期review、v1/v2保留溯源；v2修正独立原题数口径，v3在原数量不变的情况下进一步筛选Video-MMMU概念题，排除图结构/符号题与明显仅凭题干可答的题。

| 文件 | 用途 |
|---|---|
| `all_qa_examples.md` / `all_qa_examples.csv` | 用户要求的完整表：管线、数据集、子类、Q、A，另带原题ID |
| `{general,long,knowledge}_qa_examples.md` | 分支拆分，便于阅读 |
| `category_screening_and_shortages.md` | 全96组原始数、静态候选数、选取数与缺口 |
| `deferred_examples.md` / `deferred_qa.jsonl` | 专项待建类别和逐题暂缓原因及原例 |
| `selected_qa.jsonl` / `screened_inventory.jsonl` | 题目/答案/选项、原路径行号、子类/多标签、筛选状态 |
| `manifest.json` | 固定源版本、输入/输出哈希、脚本哈希、模型调用数和验证边界 |

提取工具：[build_three_branch_references.py](../scripts/benchmarks/build_three_branch_references.py)。它校验官方标注输入身份，只读本地七个标注文件，不读视频、不联网；输出必须在代码库外且不与输入重叠，已存在目录拒绝覆盖。需安装/提供pyarrow；本次使用已有依赖目录，没有额外下载。

```bash
python scripts/benchmarks/build_three_branch_references.py --input-root /path/to/benchmark_nonvideo --output-root /path/to/new_reference_export --curation configs/benchmark_reference_curation_2026-10-22.json
```

默认每类优先不同视频，兼顾明显视觉观察式问题；静态正则只是粗筛，会误杀也会漏过隐含音频/OCR问题。不能声称得到“已证实caption可答的所有题目”，也不能根据静态候选数推算生产通过率。需要检查的反例：题目不含“read”但答案来自姓名字幕；概念题不含“calculate”却依赖板书；情绪题实际依赖对白。发现后记录附加排除并重新生成新的导出版本，保留旧导出溯源。

本次附加排除69条原题/分类身份，原因记录于[人工可读排除配置](../configs/benchmark_reference_curation_2026-10-22.json)，只保存ID与原因，不保存原题载荷。该配置是助手依据文本的审阅记录，**不是用户人审或专家审核**。验证命令是在上面的提取命令后加`--validate-only`，核对源哈希、导出哈希、确定性回放及Markdown/CSV的原题选项答案一致性。验证记录见[本地验证与边界](three_branch_reference_validation_2026-10-22.md)。

## 8. 一手依据与迁移限制

| 一手来源 | 本项目采用的依据 | 不直接迁移的部分 |
|---|---|---|
| [Video-MME官方项目](https://github.com/MME-Benchmarks/Video-MME)及本地官方标注 | 12种task标签、long子集和原始QA | 长视频标签不自动证明需要跨段；题目也可能依赖字幕/音频 |
| [Video-MME-v2官方仓库](https://github.com/MME-Benchmarks/Video-MME-v2) | 本地`third_head`33个叶类；分组/层级原元数据保留 | 音画、精确运动、符号推理不能仅凭类别名宣称caption可答；分组评测结构不等于独立SFT题 |
| [LVBench论文§3.2–3.4](https://arxiv.org/html/2406.08035) / [官方仓库](https://github.com/zai-org/LVBench) | 六种能力可组合，多标签需保留；长上下文检索与理解并存 | benchmark时间引用不等于事件精确起止，生产绝对时间须来自实际原片索引 |
| [Video-MMMU论文§3.2](https://arxiv.org/html/2501.13826) / [官方仓库](https://github.com/EvolvingLMMs-Lab/VideoMMMU) | 六类分感知/理解/迁移；迁移会用新问题/案例图片 | 音频有用性、额外图片、公式/图表等依赖不在通用视觉caption合同内 |
| [MMVU论文§3.1–3.3](https://arxiv.org/html/2501.12380) / [官方仓库](https://github.com/yale-nlp/MMVU) | 27学科；面向视觉现象的教材概念引导，专家检查视频必要性 | 专家团队、教材依据和人工质控不会因使用相同task名称自动获得 |

原标注仓库与固定revision及哈希见参考导出manifest；下载范围记录见[非视频下载清单](benchmark_nonvideo_local_download_2026-10-22.md)。上述过滤和三管线划分是本项目工程判断，不是论文声称“这些类别适合LLaVA三级caption”的结论。

## 9. 下一步实施前还需冻结

1. Knowledge候选数、fit/balance拆分、三分支是否有混合权重，以及Knowledge模型/预算；本轮没有擅自补值。
2. 将96个来源分类映射到有限、互斥尽量清晰的生产能力task；MMVU subject单列；冻结首批启用/实验/暂缓名单。
3. 新分支及Long检索的prompt、模板、schema与A7任务证据合同，同时修改；只改提示不改校验会造成新题被旧多段规则拒绝。
4. 用用户MP4小批次验证caption覆盖是否足够支撑领域现象、因果与叙事。如果不足，应关闭任务/弃答；未来专项另立项，不暗中恢复A4或提高采样/调用量。

验收反证：只靠改问法造成同一所求重复、把单帧颜色题都标Long、把常识问答都标Knowledge、模型凭知识捏造视频事实、给缺查询图的题补图意、用稀疏caption精确计数。出现任一情形，说明该类路由或证据合同没有闭合。
