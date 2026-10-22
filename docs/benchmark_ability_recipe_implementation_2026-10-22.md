# 面向 benchmark 能力的三分支 QA 构造实现

日期：2026-10-22。当前方案名 `benchmark_v1`。本文件覆盖早期“两分支、Knowledge 尚未接入”的设计状态；历史文档仍保留当时证据。实现位置为独立仓库 `Tiachi/video-sft-builder`，不是父级 Dataset 仓库。

## 1. 本次决策与验收边界

**目标是迁移 benchmark 的解题操作、证据需求与干扰项结构，而不是复制原题或把简单题改标签。** General 18 个能力 task，Long 8 个，Knowledge 6 个。原参考表中的 96 个来源分类与生产 task 不是一一对应关系。完整对应关系在 [96 类能力映射](../configs/benchmark_capability_coverage.json)；其中 `caption_conditioned_transfer` 仅表示适合当前证据粒度，`partial_transfer` 表示只迁移一部分能力，`deferred` 不进入该来源类的生产覆盖声明。均不代表 benchmark 分数已提高。

当前映射为33类caption条件迁移、39类部分迁移、24类暂缓。相比原参考表75类“可条件借鉴”，生产版额外暂缓General的Counterfactual Reasoning、Future Event Prediction、Symbolic/Metaphorical Interpretation三类：参考样例可供研究，但不能保证现有caption链可靠地产出等价训练题。Knowledge的显式条件变式仍限于可验证规则，不等于完整支持这些General专项。

| 项目 | 当前决定 |
|---|---|
| General | 每个适配视频 2 条适配优先＋3 条均衡优先，最多发出 5 条候选 |
| Long | 1＋2，最多 3 条候选；不设最低时长；检索可以单段，跨段任务仍须多段 |
| Knowledge | 用户最新确认 2＋3，最多 5 条候选；可用专业先验，视频观察必须是解题必要条件 |
| 最终保留 | 所有最终自动审核通过者保留；拒绝不改、不补题，不按配比丢弃合格项 |
| 题型/配比 | OE/单选 MCQ=7:3；MCQ 内 3/4/6 项=1:7:2；中文/英文=3:7，均为全局软目标 |
| CoT | 当前不生成；最终 `cot=null`，之后独立链路处理已发布 QA＋视频 |
| 审核 | A7 每条一次原片完整视觉＋文本；没有额外专家 API、反复观看或 A4/A10 |
| 实现 | 调度、生成协议、排序/定位编译、三分支审核、导出、费用与能力报告已接入 |
| 验证 | 本地合成和协议测试；没有运行真实模型，也没有测 benchmark 改善或专业正确率 |

最终回归为204项（202通过、2项真实FFmpeg环境相关跳过）；详细故障注入、调用统计和未验项目见[验证记录](benchmark_ability_recipe_validation_2026-10-22.md)。

参考题库原始问答不被加载到模型 prompt，也不提交 Public Git。保留能力统计与人工编写的问法风格，避免把测试集原答案直接当作本视频标签。原始视频若本身与 benchmark 重合，本轮仍没有完成污染排查，不声称已经去污染。

## 2. 生产能力分类

表中“事实/窗口”是最低要求，不是足以证明语义成立的充分条件。不同角色必须引用不同事实；多个事实不能只是同一句观察换 ID。窗口来自原片 L1 的既有范围，不将粗范围当精确事件边界。

### General：18 个 task

| task | 真正考察/答案要求 | 最少事实/窗口 | 题型 |
|---|---|---:|---|
| scene_description | 场景与环境类型，有画面依据，不猜地名故事 | 1/1 | OE、MCQ |
| entity_identification | 目标对象类别或可见身份描述，不猜姓名背景 | 1/1 | OE、MCQ |
| entity_attribute | 被询问实体的可见属性，不能改答动作 | 1/1 | OE、MCQ |
| spatial_relation | 给定参照系下的空间关系 | 1/1 | OE、MCQ |
| action_description | 实际动作、参与对象或操作 | 1/1 | OE、MCQ |
| event_order | 至少三个可观察事件的真实先后，程序构造排列 | 3/1 | OE、MCQ |
| state_change | 同一实体前后状态/存在变化 | 2/1 | OE、MCQ |
| temporal_comparison | 两阶段按指定标准比较，不只逐段复述 | 2/1 | OE、MCQ |
| observable_causality | 可见干预、作用与结果，先后不是充分因果依据 | 2/1 | OE、MCQ |
| video_synopsis | 多观察支持的主旨、关键过程 | 2/2 | OE、MCQ |
| qualitative_motion | 定性方向、运动状态或快慢趋势，非速度/轨迹坐标 | 2/1 | OE、MCQ |
| object_appearance_order | 身份可辨实体的首次出现顺序，不能靠总数 | 3/1 | OE、MCQ |
| scene_transition | 前后场景及转换关系 | 2/1 | OE、MCQ |
| compositional_relation | 同时使用两个不同必要事实才能回答的关系 | 2/1 | OE、MCQ |
| visible_interaction | 行为回应、协作与可见角色变化，不猜内心/对白 | 2/1 | OE、MCQ |
| narrative_turning_point | 情境、转折事件、可见后果的联系 | 3/1 | OE、MCQ |
| visual_anomaly | 与可见基线冲突的变化，不揭秘隐藏机关 | 2/1 | OE、MCQ |
| demonstrated_method_application | 将视频明确示范的方法用于题干显式变式 | 2/1 | OE、MCQ |

后者可以使用题干明确给出的假设，但不能凭空制造视频条件、额外查询图片或精确数值求解。General 的推理必须来自观察或视频展示的方法；外部专业规则转入 Knowledge。

### Long：8 个 task

| task | 真正考察/答案要求 | 最少事实/窗口 | 题型 |
|---|---|---:|---|
| long_context_retrieval | 在完整上下文中定位/消歧目标并回答该处信息，非任意单帧套标签 | 1/1 | OE、MCQ |
| segment_retrieval | 事件所在的唯一既有粗时间窗口 | 1/1 | OE、MCQ |
| long_state_comparison | 不同片段中状态/情境按标准比较 | 2/2 | OE、MCQ |
| cross_segment_qa | 至少两段事实均为必要的关系组合 | 2/2 | OE、MCQ |
| long_event_order | 至少三个不同片段的事件排序 | 3/3 | OE、MCQ |
| long_causal_link | 跨段原因与后果的可见联系，不能只凭先后 | 2/2 | OE、MCQ |
| event_timeline | 至少三个阶段按真实时间组织，可引用粗时间范围 | 3/3 | **仅 OE** |
| hierarchical_summary | 开头、中间、结尾的主要阶段与联系 | 3/3，覆盖三等分 | **仅 OE** |

定位 MCQ 的时间范围由程序从现有窗口选取并渲染，窗口不够给定选项数时在调度前排除组合；例如只有三个窗口不调度六项定位 MCQ。是否唯一、是否真正需要整片检索仍由 A7 看原片判断。短片允许适配 Long，所以本项目 Long 名称不等于原视频必然很长。

### Knowledge：6 个 task

| task | 视频前提＋专业操作 | 最少事实/窗口 | 题型 |
|---|---|---:|---|
| knowledge_concept_identification | 用必要可见特征区分专业概念/方法，不能只靠定义 | 1/1 | OE、MCQ |
| knowledge_mechanism_explanation | 根据实际条件与结果解释机制 | 2/1 | OE、MCQ |
| knowledge_method_application | 针对视频中的条件选择或应用方法 | 1/1 | OE、MCQ |
| knowledge_condition_comparison | 对照可观察条件，并应用定性规则 | 2/1 | OE、MCQ |
| knowledge_evidence_diagnosis | 利用可区分证据辨析原因/问题，多解则弃题 | 2/1 | OE、MCQ |
| knowledge_procedure_rationale | 解释此条件下该操作的专业目的与原理 | 2/1 | OE、MCQ |

Video-MMMU 的 6 个领域、MMVU 的 27 个学科仍然是来源分组。不能仅因一道数学题被原表保留，就认为任意数学讲座 caption 能生成同等问题。

你的源类别顺序完整保存在 registry.source_context：学术活动与栏目、软件开发、数学、人工智能大模型、计算存储与新跑、通信与网络、学者访谈、交叉新兴领域、行业战略与商业洞察、网络与信息安全、电子与电磁工程、材料化学与生物能源、智能终端、多媒体与图形图像、前沿探索与科普、质量与制造工程、智能汽车。“计算存储与新跑”暂保留你的原文，不擅自改名。

这份列表仅传给 Knowledge 的适配 prompt 作弱偏好，**没有学科配额、自动给每段视频贴学科，也不改变 task 小根堆的均衡权重**。较适合专业概念辨识、方法条件、机制解释和操作目的；必须先看该视频 caption 真正有哪些证据。软件屏幕需要精读代码、讲座需要听懂语音、数学需要读公式的情况，当前粗 caption 管线很可能没有所需信息，应弃题。清晰实验现象、设备操作、宏观动画、过程演示更有机会适配，但实际产率尚未验证。

## 3. 四模块的当前链路与产物

| 模块 | 输入 | 主要处理 | 输出 | API |
|---|---|---|---|---|
| 1 预清理 | 只读 MP4 文件/文件夹/已接收直链、冻结配置 | 完整清单、元数据、损坏/画质/重复检查、完整窗口与容量前检 | manifest、媒体检查、分段计划、reject/blocked 事件 | 无模型 API |
| 2 三级 caption | 合格原片与完整分段计划 | L1 局部描述；L2 当前非重叠块视觉＋已有累计文字；L3 合并；整片稀疏检查 | 全部 L1/L2、完整 L3 bundle、稀疏检查证据与 gate 结果 | A1、A2、C_GATE；L3 文字合并不另调模型 |
| 3 三分支 QA | 同一已通过 gate 的 caption bundle、窗口 ID、任务注册表、模板、批次计数 | fit 优先→均衡；证据角色/规则账本；排序/定位编译；本地检查 | candidate、局部 reject、调度与模板记录 | General、Knowledge 用 A3；Long 用 A5，均为文本调用 |
| 4 逐题质量检查与导出 | 一条程序处理后的 QA＋必要事实/规则＋原始完整视频 | 一次 A7 基础质量＋能力审核；失败 reject；通过全保留；分支完成与全覆盖独立核验 | 三份训练候选 JSONL、外置能力证据、费用/保留率/拒绝统计、人读报告 | 每条本地合法 QA 一次 A7 |

模块2采样、分块、L3 gate、原片只读与既有不静默截断规则不变。任何 caption gate 拒绝后都不会运行三分支。

核心代码：

```python
for video in eligible_videos:
    captions = existing_three_level_caption_pipeline(video)
    if not sparse_visual_gate(captions, video):
        reject_caption(video)
        continue
    for branch in [general, long, knowledge]:
        dispatch_one_fit_request(branch)  # 分别含 2/1/2 个槽位
        # 每次处理完候选和 A7 后再调度下一槽；拒绝回减计数
        while balance_emitted < branch.balance and attempts < branch.limit:
            task = least_accepted_eligible_task(branch)
            language, form, option_count = greatest_global_deficit(task)
            generate_or_abstain(task, language, form, option_count)
            # 弃题可换任务/形式；一旦产出候选，哪怕不合格，也消耗槽位
        # 每个实际产出：本地约束→程序编译→一次原片 A7→通过或 reject
```

小根堆按本分支当前已通过/待审候选数排序，再以最近调度与稳定种子打破平局；A7 拒绝会回减计数。语言、题型、选项数量根据三分支共享的已保留计数缺口选择，合法形式优先。适配阶段预分配语言/题型，再让模型选最适配 task。任务穷尽、形式不可用或达到尝试上限就停止，不强造。各分支没有确认混合配额；最终量取决于源内容和审核通过率。

General/Long 保留原配置的 12/5 次均衡尝试上限，以避免扩大 task 表后自动扩大账单；因此不保证逐个试遍新增的18/8类。Knowledge 默认9次是6类＋3槽的有限预算。它们都是可见的工程初始值，可在未来构建的私有配置中调整；不是为了凑满QA而无限重试。

## 4. 防止“任务名对、题目错”

新增 `assessment`，只放中间记录与 sidecar，不加到最终 12 字段 JSON 顶层：

```json
{
  "operation": "knowledge_mechanism",
  "roles": {"conditions": ["f1"], "observed_result": ["f2"]},
  "criterion": "需要解释这个条件下的可见结果，而非识别动作",
  "video_necessity": "必须看到实际条件与现象，单靠学科词无法确定",
  "knowledge": {
    "domain": "示例领域",
    "concept": "示例概念",
    "rule": "这里记录适用规则，不把规则冒充视频观察",
    "rule_source": "model_prior_unverified",
    "premise_fact_ids": ["f1", "f2"],
    "applicability_note": "这里简述适用条件；不是完整 CoT"
  },
  "distractors": []
}
```

程序检查 operation 精确匹配、角色键及最小数量、角色互斥、所有必要事实有角色、重复 claim、不存在的事实/窗口、Knowledge 规则来源与前提、OE/MCQ 字段一致性、错误项证伪依据完整。程序按注册表盖上可信 `task_contract`，并拷贝引用 `caption_evidence` 给 A7，不接受模型自己降低门槛。

A7 在原来的 11 个基础检查之外，**同一次调用**增加 8 项：operation_match、caption_faithfulness、video_necessity、answer_contract、reasoning_validity、knowledge_rule_validity、distractor_validity、retrieval_scope。任务要求项必须 pass；MCQ 干扰项必须 pass；fail/insufficient/必需项 not_applicable 都拒绝。模型单次判断仍可能错误，结构检查不是语义正确证明，且本轮没有人审或专业知识库核验。

排序由模型提供已绑定事实的 3—6 个事件和真实顺序，程序用随机数打乱展示，事件编号 E1…与选项 A…分离，生成错误全排列再随机打乱选项、重映射答案与证伪记录。程序不凭排序数组证明真实时序，A7 仍核视频。定位由现有窗口 ID 生成原片绝对范围；不支持从 caption 捏造精确起止。

## 5. 问法风格与提示词

共 **256 条原创种子模板=32 task×4 种风格×2 语言**。共享操作的 task 仍有独立 template_id 与答案约束。不是 256 个已填好的 benchmark 原题，也不是语言表达多样性已经实测通过。调度按模板使用数轮转，生成模型根据实际证据填充并自然微调；A7 继续检查模板化、答案泄漏与任务匹配。

| 文件 | 用途 |
|---|---|
| [benchmark_task_registry.json](../configs/benchmark_task_registry.json) | 能力名称、操作、事实角色、窗口/答案/审核约束 |
| [benchmark_question_templates.json](../configs/benchmark_question_templates.json) | 完整 256 模板、占位符、风格、题型与干扰项类型 |
| [英文生成原文](../prompts/benchmark/generation.system.en.txt) / [完整中文翻译](../prompts/benchmark/generation.system.zh.txt) | 三分支共用生成协议，生产使用英文版本 |
| [英文审核原文](../prompts/benchmark/audit.en.txt) / [完整中文翻译](../prompts/benchmark/audit.zh.txt) | 单次 A7 的全部基础与能力检查 |
| [build_benchmark_recipe.py](../scripts/build_benchmark_recipe.py) | 可重复编译三个配置资产；无参数只检查漂移，`--write` 明确更新 |

任务专门化主要由注册表、每个操作的模板和 A7 所需项承载，不为每个 task 增加独立模型调用。

## 6. 调用次数、费用边界与模型接入

| 部分 | 通常每视频调用数 | 配置的最多尝试数 | 媒体 |
|---|---:|---:|---|
| A1 | n1 | n1 | 每个 L1 分块视频 |
| A2 | n2 | n2 | 每个新增 L2 分块视频＋累计文字 |
| C_GATE | 1 | 1 | 全片稀疏图＋L3/相应文字 |
| General A3 | 1 次双槽适配＋3 次均衡=4 | 1＋12=13 | caption/事实等文本 |
| Long A5 | 1 次单槽适配＋2 次均衡=3 | 1＋5=6 | 同上 |
| Knowledge A3 | 1 次双槽适配＋3 次均衡=4 | 1＋9=10 | 同上，含弱领域偏好 |
| A7 | 最多 5＋3＋5=13 | 13 | **每题一次完整原视频＋对应文本** |

通常指所有槽位首次成功生成、本地检查通过并接受逐题审核，不保证最终通过。该路径总调用 `n1+n2+25`；在默认尝试上限下，保守调用上界 `n1+n2+43`。这是推理调用数，不含上传、下载、显式连通性探测等辅助 HTTP。生成 task 不适配可多耗文本尝试，模型拒绝/本地失败可减少 A7；预算可更早 blocked。Knowledge 相对原两分支通常新增 4 次文本＋最多 5 次全片 A7，长片额外费用可能明显，UI 会显示。

一小时视频若 L1=10s、L2=30s，没有特殊短尾，则 n1=360、n2=120，通常 505 次、默认保守上界 523 次；**不是 505 次整片视觉**，其中完整原片审核最多 13 次。金额须用实际 provider 模型、视频 token 规则、生效采样/分辨率和报价计算，不把合成测试 token 当真实价格。

Knowledge 复用 **A3 文本端点与价格配置**，不新增 `QA_KNOWLEDGE` API 角色；General 和 Knowledge 费用仍通过 branch 元数据分开报表。Long 用 A5；A7 用既有审核端点。Qwen/OpenAI-compatible/vLLM 适配层沿用；vLLM 仍需明确 served model、媒体路径、容量及采样能力，不因有兼容 URL 就假定视频支持。

## 7. 启用、旧版本保护与输出

新安装的终端配置默认选择 `benchmark_v1`。已有私有配置缺少该字段时保持 `legacy_v1` 两分支，不自动迁移或增加费用。在终端输入：

```text
/recipe benchmark_v1
/new 本次名称
/run
```

切换只影响之后 `/new` 的运行；已有 build 的 runtime.json 不变。查看 `/recipe`；回到旧方案用 `/recipe legacy_v1`。`/demo` 使用所选方案走纯合成链路，不调用付费 API。先查看预览与预算，再正式执行。代码资产指纹发生变化时，旧有已付费运行仍由原有保护拒绝混用；不要手改指纹或盲目新建轮次重付，需沿既有 caption-only recovery 规程处理。

最终导出分别是 general.jsonl、long.jsonl、knowledge.jsonl，结构统一，仍只有 12 个顶层字段。新版本 task.pipeline 分别为 benchmark_general_v1、benchmark_long_v1、benchmark_knowledge_v1；benchmark_refs 不填“这道合成题就是原 benchmark GT”。所有 caption、专业规则、事实角色、模板风格、审核详情都在最终训练记录外部保存：

- exports/<version>/ability_evidence.jsonl：按 sample_id 关联，包含全部本地合法候选及其质量结论；manifest 记录 hash。
- reports/<version>/benchmark_capability_coverage.json：96 来源类映射、32 task 产出/通过/本地拒绝、问法风格、Knowledge 实际领域分布、共享 caption/三分支的请求与费用。
- reports/<version>/review.md：可直接阅读每题、选项、答案、证据与审核。只是审阅界面，不代表人审已执行。
- 原有 state/reject/source_by_stage.csv/stage_by_source.csv/summary.json：保留中间结果、各阶段与来源筛除量、真实使用 token/费用和未完成位置。

报告独立检查三分支是否终结，缺 Knowledge 也不能显示 complete。导出和报告 sidecar 做内容 hash 检查，篡改不静默覆盖。quality 分数、学生 token/processor 验收仍保持原有待验状态，不虚构数值。

## 8. 依据、备选与剩余风险

| 一手依据 | 可迁移的证据 | 本项目采用 | 限制/可推翻条件 |
|---|---|---|---|
| [Video-MME-v2 官方库](https://github.com/MME-Benchmarks/Video-MME-v2) | 扩展能力分类与任务差异 | 对照原参考表映射操作/答案形式，保留部分覆盖与专项暂缓 | 若模型仍只生成简单识别题，即使标签均衡也失败 |
| [LVBench 官方库](https://github.com/zai-org/LVBench) | 长上下文信息检索、事件理解、总结、推理和时间定位等 | 分离单段检索、跨段组合、全局结构 | 完整上下文不可见、定位不唯一、只有孤立帧即可答时不合格 |
| [Video-MMMU 论文 §3.2](https://arxiv.org/html/2501.13826) | 领域与认知操作不能混同，需知识应用 | 学科作条件，任务为概念/机制/应用等操作 | 缺查询图、公式/细节或实际条件的题不能靠通用 caption 复刻 |
| [MMVU 论文 §3.2](https://arxiv.org/html/2501.12380) | 视频必要性与专业知识质量控制 | 必要视频前提和规则分离、A7 同时检查 | 自动生成＋单模型审核不等于原数据专家保证 |

以上是构造借鉴与工程推断，**不是这些论文直接验证了本项目 32-task taxonomy、模板数量或产率**。推荐默认是保守弃题、保留可审计证据，不增加审核轮次。替代方案是按原 96 分类分别建堆，但容易把学科、形式、模态依赖与能力混成 task，并强造当前粒度不支持的题，因此本版不采用。

尚未实现的专项：细节 OCR/字幕、精确计数、密集动作次数、精确时刻边界、音频/对白、查询图依赖、细粒度公式/程序语义、不可见未来/隐喻/内心。当前能力即使有对应 task，也只覆盖 caption 明确记录的子集。Knowledge 高比例讲座/访谈可能大量弃题；不能为了 5 条配额补造专业内容。后续需要真实小批样本统计每 task 的适配、拒绝、视频必要性和题目难度后，才有依据改进采样或专业审核。本轮没有付费试跑、人审、服务器执行或实际 benchmark 增益结论。
