# L1/L2 采样与 General、Long 任务/模板/产出方式核对

日期：2026-10-22。本项目审查基线：fafd14210dcbea97ea8f097142728ec8363301ee。本文只核对现有实现，不修改配方、不调用付费模型、不重跑已有轮次。

## 1. 先回答：是否确保 L1、L2 分别读取 10 帧、30 帧？

**不能这样表述。当前 L1/L2 的 10/30 是秒数，当前配方为 2 FPS，标准片段的名义采样量约为 20/60 帧。项目能够核查切片范围与请求参数，尚不能独立确认云端实际处理了多少帧。**

| 项目 | L1 / A1 | L2 / A2 |
|---|---|---|
| 标准视觉输入范围 | 当前非重叠 10 秒片段 | 当前非重叠 30 秒片段 |
| 当前配方 | 2 FPS | 2 FPS |
| 标准片段的名义采样量 | 约 20 帧 | 约 60 帧 |
| 实际发送 | 一份派生 MP4 + FPS、像素预算参数 | 一份派生 MP4 + FPS、像素预算参数 |
| 额外文本 | 前一个累计 L2、当前块已产的 L1 | 前一个累计 L2、当前块的新 L1 |
| 输出描述覆盖 | 当前 L1 窗口 | 从原片起点到当前块结束的累计文本 |
| 是否本地抽固定数量图片再发送 | 否 | 否 |
| 是否拿到云端实际帧数回执 | 未实现 | 未实现 |

**L2 视觉范围不会从 30 秒增长成 60 秒、90 秒。增长的是累计描述的文本范围。** 例如第二次 L2 发送 30–60 秒 MP4、前一份 0–30 秒累计描述及本块 L1，输出 0–60 秒累计描述。L3 直接引用最后一份 L2，不额外调用一次模型。

[当前配方](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/terminal.example.json)、[配置编译](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/settings.py#L217)、[caption 编排](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/pipeline.py#L83)。

### 1.1 当前已实现的保障，及其边界

| 层级 | 当前保障 | 可以证明什么 | 不能证明什么 |
|---|---|---|---|
| 全片窗口规划 | 在付费 caption 请求前规划全量 L1/L2；极短尾段并入上一段；不降低 FPS | 计划覆盖原片完整范围 | 云端抽帧细节 |
| 切片落盘 | FFmpeg 生成只含视频的派生 MP4；检查实际时长容差、来源标识和校验和 | 发出的切片与计划相符，原片不改动 | 模型内部没有下采样 |
| 请求容量前检 | 检查片段时长 × FPS、帧数预算及原片帧率；超容量 blocked | 客户端不会主动悄悄减少 FPS 或跳过窗口 | 供应商的内部上限、解码/抽帧取整与参数支持均已实测 |
| 请求留痕 | 保存 profile、媒体范围、请求/上下文指纹 | 请求了什么 | 实际生效帧数；该字段明确为 null |
| bundle 完整性 | L1/L2 数量、顺序、边界、最后 L3 全片终点逐项验证 | caption 产物与完整计划一致 | 每个 caption 事实都正确、每个短事件都被看到 |

代码：[caption_plan.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/caption_plan.py)、[切片时长核验](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/media.py#L171)、[Qwen 请求体](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/provider.py#L137)、[request_view 留痕](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/provider.py#L285)。

请求记录目前明确写入：

~~~json
{
  "provider_effective_sampling": null,
  "observability": "requested_view_only_native_preprocessing_unobserved"
}
~~~

预置的 sampling_verified=true 是配置中的能力声明，**不能当成本轮实际 20/60 帧验收成功的证据**。此外，本地 max_frames 容量前检不等于给 OpenAI 兼容接口传入了一个服务端 max_frames 覆盖参数：当前 Qwen 请求体传 FPS、max_pixels、total_pixels，没有传 max_frames。供应商实际行为仍须按具体端点核实。

阿里云文档说明 fps 控制时间采样间隔，且服务端存在帧数上限；其 max_frames 覆盖参数仅支持 DashScope SDK。故从“请求设置 FPS”推导“本轮内部精确处理固定帧数”并不充分。[官方视频输入说明](https://help.aliyun.com/zh/model-studio/vision)

尾段和时间取整也会使帧数不同于整数片段的简单乘法。此前 60.026693 秒原片最后一段会包含小数尾部，因此不能把所有 L1/L2 统一写成严格 20/60，更不能写成严格 10/30。本文不把 duration×fps 或 ceil(duration×fps) 冒充服务端实测帧数。

如果用户确实要“10 秒约 10 帧、30 秒约 30 帧”，名义配置应是 1 FPS；**当前仍保留此前选定的 2 FPS，未做修改。** 若将来要求可审计的精确帧清单，可选显式图片序列输入；这属于另一种媒体合同，须另行验证，本文不自动切换。

### 1.2 验证状态

- **代码核对：** 本文依据上述固定提交逐项读取实现。
- **用户提供的服务器运行证据：** video1_test2 显示 L1 6/6、L2 2/2、L3 完成，C_GATE 拒绝，branches 为空。它证明本轮计划内 caption 单元完成，不能证明供应商内部实际帧数，也不能证明 General/Long/A7 已真实跑通。
- **仍未核验：** 该 API 端点实际采样帧数、每种 task 的真实生成质量、最终训练 processor 验收。
- **建议的验收门槛（尚未执行）：** 若要声称精确采样，需取得供应商实际预处理元数据，或验证显式帧序列传输合同；单看 usage token 总数或询问模型“看到了多少帧”不构成精确回执。

## 2. General 和 Long 当前 task 分类

来源：[任务注册表](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/task_registry.json)。以下是代码实际启用的白名单，不是 VideoChat3 官方 taxonomy。注册表中 proposed_enabled 这一历史名称目前被 Scheduler 当成启用条件；旧 target_weight 数字不参与现行均衡堆。

### 2.1 General：9 类

| task | 中文名称 | family | 题型 | 最少事实数 | 证据要求与范围 |
|---|---|---|---|---:|---|
| scene_description | 场景描述 | visual_perception | OE / 单选 MCQ | 1 | 清晰可见的环境特征，不猜具体地名 |
| entity_attribute | 实体属性 | visual_perception | OE / 单选 MCQ | 1 | 唯一可识别实体及可见属性 |
| spatial_relation | 空间关系 | visual_perception | OE / 单选 MCQ | 1 | 同时刻、有明确参照物的空间位置 |
| action_description | 动作描述 | action_understanding | OE / 单选 MCQ | 1 | 显著动作、参与者与作用对象 |
| event_order | 事件先后 / 排序 | temporal_understanding | OE / 单选 MCQ | 2 | 明确事件及先后；启用程序排序编译时须提供 3–6 个事件 |
| state_change | 状态变化 | temporal_understanding | OE / 单选 MCQ | 2 | 同一对象的前后状态，身份对应清楚 |
| temporal_comparison | 时段比较 | temporal_understanding | OE / 单选 MCQ | 2 | 两个时间窗口中同一比较维度的差异 |
| multi_fact_composition | 多事实组合 | evidence_reasoning | OE / 单选 MCQ | 2 | 回答确实需要组合至少两个事实 |
| observable_causality | 可见因果 | evidence_reasoning | OE / 单选 MCQ | 2 | 有可见作用过程与结果；不能把时间先后当因果 |

“最少事实数”是程序结构门槛，事实是否真实、是否各自必要仍交给 A7；列出两个 fact_id 本身不代表推理有效。

### 2.2 Long：3 类

| task | 中文名称 | family | 题型 | 最少事实数 / 不重叠窗口数 | 额外要求 |
|---|---|---|---|---|---|
| cross_segment_qa | 跨段问答 | long_video_understanding | OE / 单选 MCQ | 2 / 2 | 至少两段均为回答所必需；单帧、单独一段或语言常识不能充分回答 |
| event_timeline | 事件时间线 | long_video_understanding | 仅 OE | 3 / 3 | 按时间组织显著事件，使用已有粗窗口；不声称精确动作边界 |
| hierarchical_summary | 分层全局总结 | long_video_understanding | 仅 OE | 3 / 3 | 开始、中间、结束均有证据；本地按视频三等分检查覆盖，A7 再审 |

Long 不设置原片最低时长；短视频也可进入，但需要满足对应的多段证据门槛。其名称代表专项能力，而非时长准入。

[本地 task/证据校验](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/quality.py#L115)、[A7 判定校验](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/quality.py#L220)。

### 2.3 已登记但不启用

| task | 所属分支 | 当前状态 | 原因 |
|---|---|---|---|
| visible_text | General | deferred_disabled | 缺少可靠高清 OCR 真值 |
| fine_grained_motion | General | deferred_disabled | 缺少密集局部运动证据 |
| action_count | General | deferred_disabled | 缺少全实例连续覆盖及动作边界 |
| recurring_event_aggregation | Long | experimental_disabled | 不保证“每次/全部/总次数”，当前不生产 |
| segment_retrieval | Long | experimental_disabled | 只有粗窗口，没有精确定位验证 |

当前模板库仅包含 12 个启用 task，没有给这 5 个停用 task 配生产模板。

## 3. 题型模板库：是什么、怎么选

模板原文件：[configs/question_templates.json](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/question_templates.json)。现有 **12 task × 2 语言 × 每语言 8 条 = 192 条问法模板**：General 144，Long 48。附录给出全部 192 条原文，下面先列每类的 .01 代表模板。

这些是本项目自编的问题表达骨架，**不是 VideoChat3 官方生产 prompt**。每类 8 条主要是表达变体，不能把“192 条”理解成 192 种独立语义任务。

模板还统一声明 3 种 answer_styles：concise_fact（简洁事实）、complete_sentence（完整句子）、comparison_or_sequence_when_required（任务需要时作比较或序列回答）。当前 Scheduler 会把这些元数据随选中模板发送，但不单独调度答案风格，也没有一套独立的标准答案/MCQ 干扰项模板库；答案与一般 MCQ 干扰项由模型依证据生成，排序排列由程序生成。模板文件的 authored_not_model_tested 表示已编写、尚未逐模板实测，不能理解成已验证的生产质量。

| 分支 | task | 中文模板 .zh.01 原文 | 英文模板 .en.01 原文 | 生效题型 |
| General | scene_description | {time_ref}，主要活动发生在怎样的环境中？ | What kind of setting contains the main activity {time_ref}? | OE / MCQ |
| General | entity_attribute | {time_ref}，{entity}的{attribute}是什么？ | What is the {attribute} of {entity} {time_ref}? | OE / MCQ |
| General | spatial_relation | {time_ref}，{entity}相对{reference}位于哪里？ | Where is {entity} relative to {reference} {time_ref}? | OE / MCQ |
| General | action_description | {time_ref}，{actor}对{object}进行了什么操作？ | What does {actor} do to {object} {time_ref}? | OE / MCQ |
| General | event_order | {event_a}与{event_b}，哪一个先发生？ | Which happens first, {event_a} or {event_b}? | OE / MCQ |
| General | state_change | {time_a}到{time_b}，{entity}的状态发生了什么变化？ | How does the state of {entity} change from {time_a} to {time_b}? | OE / MCQ |
| General | temporal_comparison | {aspect}在{time_a}和{time_b}有什么不同？ | How does {aspect} differ between {time_a} and {time_b}? | OE / MCQ |
| General | multi_fact_composition | 结合{evidence_a}和{evidence_b}，回答：{relation_query} | Using both {evidence_a} and {evidence_b}, answer: {relation_query} | OE / MCQ |
| General | observable_causality | 画面中什么直接造成了{outcome}？ | What visible action directly causes {outcome}? | OE / MCQ |
| Long | cross_segment_qa | 结合{segment_a}与{segment_b}，{relation_query} | Using both {segment_a} and {segment_b}, answer: {relation_query} | OE / MCQ |
| Long | event_timeline | 请按先后概括{scope}的主要事件。 | Summarize the main events in {scope} in chronological order. | 仅 OE |
| Long | hierarchical_summary | 请概括{scope}的主要过程，说明各阶段之间的联系。 | Summarize the main process in {scope} and the connections between its stages. | 仅 OE |


### 3.1 槽位填什么

| 槽位 | 填写内容示例 | 约束 |
|---|---|---|
| time_ref / time_a / time_b | 指向原片窗口的 [[TIME:w000000]] | 只能使用实际输入中的窗口 ID；编号示例不保证等于某次实际 ID |
| entity / actor / object / reference | 红衣人物、杯子、桌子 | 必须能在 caption 中对应；不能靠占位词猜实体 |
| attribute | 颜色、形状等已记录属性 | 不凭空加入 caption 没有的细节 |
| event_a / event_b | 两个有证据的事件指称 | 指称可以定位事件，但不能在题干直接泄露所问顺序 |
| aspect | 姿态、物体位置等比较维度 | 两段均有同维度观察 |
| evidence_a / evidence_b | 不泄露答案的两处证据定位描述 | 不能在题干提前陈述本应由视频提供的答案事实 |
| relation_query | 需要组合证据回答的具体所求 | 不能退化成主题识别或常识推断 |
| outcome | 可见结果的指称 | 原因必须有可见机制，不能臆测动机 |
| segment_a / segment_b | 两个必要证据段引用 | 必须来自原片不同段，非同一事实换表达 |
| scope | 整段视频、指定过程 | 时间线/总结需满足多段覆盖 |

以上示例说明数据含义；实际模板填充由 A3/A5 完成，时间标记由程序渲染。

### 3.2 OE、MCQ、排序分别如何构造

| 形式 | 构造方式 | 程序检查 |
|---|---|---|
| OE | 模型生成自然语言问题及简洁答案 | options=[]、num_options=0、correct_option_id=null；允许程序渲染原片绝对时间 |
| MCQ | 模型按分配槽位给 3/4/6 个选项与唯一正确项 | 选项非空且不重复、标签连续、答案指向唯一项；程序随机打乱并重标正确标签，A7 再检查语义唯一性 |
| 排序 OE | event_order 可返回 ordering 元数据：3–6 个事件、正确 ID 序列 | 程序随机打乱事件呈现，用映射后的事件标签生成顺序答案 |
| 排序 MCQ | 同上，正确顺序加其他排列作为选项 | 程序枚举排列空间并抽取不同干扰顺序，再打乱选项；仍为单选题 |

排序元数据目前是**可选字段**，不是每个 event_order 都强制走 3–6 事件编译；普通“两事件谁先发生”也能按注册表生成。MCQ 的 3/4/6 是选项数量，不是正确答案数量。

另一个元数据差异：模板文件对所有模板均写 supported_question_types=[oe,mcq]，但运行时取其与 task 白名单的交集。因此 event_timeline、hierarchical_summary 实际仍只产 OE；这属于模板元数据尚未收紧，不应据模板标签宣称 Long 三类都支持 MCQ。

### 3.3 模板轮转是怎样实现的

1. 调度器先决定槽位的 task（均衡阶段）或允许 task 列表（适配阶段）、语言、题型、选项数。
2. 只取 task、语言、题型兼容的模板，按“当前使用次数较少优先 + seed 确定的散列顺序”排列。
3. 当前终端入口对**每个兼容 task**取 2 条模板候选给模型；均衡槽位只有一个固定 task，适配槽位可能带多个兼容 task 的模板。不是一次把 192 条全发给模型。
4. 模型选择 template_id，填槽位并作自然改写；不能改变 task 或泄露答案。
5. 模板使用计数随候选暂存增加，A7 拒绝后回滚；不是严格用过一次后永久轮空。
6. 问法重复及模板化程度有本地/模型审核，但表面改写不能保证语义多样性。

代码：[scheduler.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/scheduler.py#L68)、[运行 prompt](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/prompts/task_scheduler/generation.system.en.txt)。

**实际运行 prompt 与旧设计稿的区别：** Pipeline 加载上面 task_scheduler 路径，再拼接排序说明。prompts/module3 下的 General/Long 中英版本是早期设计材料，当前不能把它们当作请求体原文。A3/A5 当前共用运行 system prompt，分支差异主要通过输入中的 branch、task 定义、slots 与约束传入。

## 4. 两分支具体怎样产出

### 4.1 共享输入与前置门禁

~~~mermaid
flowchart TD
  V[原始 MP4] --> C[L1 当前10秒 + L2 当前30秒视觉输入]
  C --> L3[L3 引用最终累计 L2]
  L3 --> G[C_GATE: L3 与稀疏帧核查]
  G -->|拒绝| R[reject: 不生成 QA]
  G -->|通过| X[全部 L1 + 最终 L2 + L3 + 原片窗口]
  X --> A3[A3 General: 文本请求]
  X --> A5[A5 Long: 文本请求]
  A3 --> P[本地结构/证据/时间/选项校验]
  A5 --> P
  P -->|通过| A7[A7: 原始完整 MP4 + 单条 QA]
  P -->|拒绝| R
  A7 -->|拒绝| R
  A7 -->|通过| E[全部保留，分支 JSONL 自动审核候选]
~~~

图中两分支是逻辑分支，当前执行器按 General 后 Long 串行运行，计数反馈会影响后续调度。

当前 QA context 并非只有 L3：它含**所有 L1 + 最后一份 L2 + L3 + 全部 L1 窗口**；较早 L2 保存但未一并发送。L3 与最后 L2 内容重复一份，这也是当前实现事实。模型同时收到已生成问题及证据定位，作为避免重复的参考；本地只对同分支题干做规范化精确重复检查，没有实现跨分支语义去重。

C_GATE 核查的是 L3，**不等于所有 L1 细节逐条验真**。因此 General/Long 使用的原始 L1 仍可能含错误事实，最终 A7 是必要的视觉审核环节，不能因 L3 通过就去掉它。

代码：[输入 context](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/pipeline.py#L179)、[C_GATE](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/pipeline.py#L151)、[两分支执行器](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/pipeline.py#L217)。

### 4.2 General：2 条适配优先 + 3 条均衡优先

~~~text
读取本视频 caption context
适配阶段：
    程序分配 2 个槽位的语言、OE/MCQ、选项数
    A3 在 General 白名单中为各槽位选最适配 task，返回候选或弃答
    对返回候选：本地检查 → A7 原视频审核 → 通过保留/拒绝落 reject
均衡阶段：
    最多尝试 12 次，直到已经产出 3 条均衡候选或无可调度组合
    从本批 General 最少计数 task 中调度一个
    再按全局配比缺额确定语言、题型、选项数，取兼容模板
    A3 生成 1 条候选，或说明任务不适配/形式不适配/证据耗尽
    候选进入本地检查与 A7；已发出的候选即使被拒也不补题
~~~

适配阶段 2 条由一次请求返回；不是为每条各调用一次。适配弃答不转移为额外均衡配额。均衡前的语义弃答允许换 task 或组合继续尝试，受尝试上限约束。

### 4.3 Long：1 条适配优先 + 2 条均衡优先

~~~text
读取同一份 caption context
适配阶段：
    程序分配 1 个槽位的语言、题型、选项数
    A5 从兼容 Long task 中选最适配任务，返回候选或弃答
    本地检查 → A7 原视频审核
均衡阶段：
    最多尝试 5 次，争取产出 2 条均衡候选
    从本批 Long 最少计数 task 中调度一个，再选语言/题型/模板
    A5 构造跨段 QA、时间线或全局总结，证据不足则弃答
    程序检查必要事实及不重叠窗口、总结三段覆盖 → A7
~~~

如果适配槽位被分配 MCQ，Long 兼容 task 只有 cross_segment_qa。并非强制每个视频各产一次 Long 的三种任务；这是本批次上的软均衡。

### 4.4 均衡计数口径

| 维度 | 计数范围 | 调度目标 |
|---|---|---|
| task | General、Long 分开按分支计数 | 各分支任务数量尽量均匀；较少者优先 |
| 语言 | 两分支合计 | 中文:英文 = 3:7 |
| 题型 | 两分支合计 | OE:MCQ = 7:3 |
| MCQ 选项数 | 两分支 MCQ 合计 | 3:4:6 选项题 = 1:7:2 |
| 模板 | 当前整轮 | 少用模板优先；受 task、语言、题型兼容约束 |

本地合法候选先占计数，A7 拒绝则回滚，成功接受者保留。较少 task 无法适配时可跳过，但不凭空硬造。配比为生成调度目标，不以删除已通过数据实现精确比例。

实现的堆在每次调度时按当前计数重建，并非一直驻留、单独变更键值的对象；语义上满足“每次选择当前较少 task”。排序还包含上次选择次序及 seed 散列，避免同计数任务反复抢占。

### 4.5 API 接入与次数

以下均假设本视频已经过 C_GATE，且 API/预算允许继续。

| 环节 | 发给模型什么 | 无弃答且全部产足时 | 当前尝试配置下的上界 |
|---|---|---:|---:|
| A3 适配 | caption 文本 + 2 个 General 槽位 | 1 次 | 1 次 |
| A3 均衡 | caption 文本 + 1 个固定 task 槽位 | 3 次 | 12 次 |
| A5 适配 | caption 文本 + 1 个 Long 槽位 | 1 次 | 1 次 |
| A5 均衡 | caption 文本 + 1 个固定 task 槽位 | 2 次 | 5 次 |
| 本地调度/模板选择/排序/时间渲染 | 不接 API | 0 次 | 0 次 |
| A7 | **原片完整 MP4 + 单条 QA 及证据文本** | 最多 8 次 | 最多 8 次 |

标准成功路径：**7 次文本生成 + 最多 8 次原视频 QA 审核**。有预出题弃答时，文本生成最多 19 次；提前无任务、容量/预算不足或技术失败会停止，不能解释为保证花满这些次数。A7 只审本地合格候选；本地拒绝者不增加 A7 次数。这里没有把 A1/A2/C_GATE 算进模块三下游调用统计。

候选生成目标 General≤5、Long≤3；最终通过者全部保留，没有再按数量删除。这与“不设最终数量截断”一致，但**不意味着当前生成器无限产题**。拒绝不修复、不补题；A4、A10 不存在，CoT 不在本链路。

### 4.6 输入、内部产物与最终产物

| 产物 | 内容 | 保存/用途 |
|---|---|---|
| caption_bundle | L1、L2、L3、原片绝对窗口 | 模块二交接；完整持久化 |
| dispatch / generation_input | 槽位、允许 task、语言/题型/选项数、候选模板、完整输入 | 本轮状态存储；恢复请求保持一致 |
| generation_response | request_id、video_id、facts、candidates、abstained_slots | 原始解析结果与请求记录，保留生成线索 |
| candidate | 问答、单选选项、template_id、必要 fact_id、证据窗口 | 本地检查后的内部候选 |
| quality / reject | A7 判断、逐项检查、事实视觉支持区间或拒绝原因 | 质检审计；不强塞到训练 conversations |
| exports/<version>/general.jsonl | 自动通过的 General 记录 | 本项目统一 12 顶层字段 |
| exports/<version>/long.jsonl | 自动通过的 Long 记录 | 与 General 同 schema，task.pipeline/name 区分 |
| reports/<version>/ | 留存/筛除、分来源分阶段、task/语言/题型/模板、请求账本等统计 | 便于本轮复核；不是人工真确率 |

最终记录的两分支标识分别为 academic2m_inspired、lv116k_inspired；cot=null。当前 quality.verify=auto_pass、quality.score=null，tokens.status=pending，训练视频精确采样字段也为 null。**这是自动审核候选导出，不是已经完成真实 token 统计和训练 processor 验收的数据发布。**

代码：[导出记录及文件](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/reporting.py#L30)、[统计报告](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/reporting.py#L100)。

## 5. 到底怎样参考 VideoChat3？

### 5.1 上游查证边界

本轮重新读取官方论文和仓库，并经 GitHub API 核对 main，当前仍是 **015f52eb2ea70b5abda30192aee18034f2c5f13b**，与此前详细检索相同。

- [官方仓库固定版本](https://github.com/MCG-NJU/VideoChat3/tree/015f52eb2ea70b5abda30192aee18034f2c5f13b)。
- [官方训练代码说明](https://github.com/MCG-NJU/VideoChat3/blob/015f52eb2ea70b5abda30192aee18034f2c5f13b/xtuner-videochat3/README.md)。
- [官方 JSONL loader](https://github.com/MCG-NJU/VideoChat3/blob/015f52eb2ea70b5abda30192aee18034f2c5f13b/xtuner-videochat3/xtuner/v1/datasets/vlm_jsonl.py)。
- [Academic2M 成品数据](https://huggingface.co/datasets/MCG-NJU/VideoChat3-Academic2M)。
- [LV116K 成品数据](https://huggingface.co/datasets/MCG-NJU/VideoChat3-LV116k)。

**此前公开范围内仍未定位 Academic2M/LV116K 的完整生产合成脚本和 prompt；本轮没有出现新版本入口。训练代码中的 data pipeline/loader 是“读现成标注用于训练”，不能等同于“从 MP4 合成新标注”。** 不将“未定位”扩大为作者永远没有提供任何相关代码。

详细检索范围和固定快照：[此前代码入口审计](llava_video_videochat3_pipeline_code_search_2026-10-20.md#5-videochat3本轮究竟查到了什么)。

### 5.2 方法借鉴和未复现部分

| 对应分支 | 上游方法要点 | 本项目采用 | 没有采用/不能继承 |
|---|---|---|---|
| General ↔ Academic2M | 以既有学术标签约束视觉增强答案，再检查语义一致性 | 任务约束、证据引用、回答可核查、审核后保留 | 只有 MP4，无原学术 GT；没有独立增强步骤 A4，不是原标签约束的答案重写 |
| Long ↔ LV116K | 分段核验后聚合，合成跨段 QA、时间线与定位 | 有时间窗口的 caption 输入；跨段必要性；时间线；A7 视觉审核 | 固定 10/30 秒窗而非场景切分；未复现独立逐段 judge 或精确 grounding 专家 |
| hierarchical_summary | 全片描述的组织思想可参考 | 开始/中间/结束结构与程序覆盖门槛 | 本项目 task 名称及约束自定，非声称官方同名 task |

原方法依据：[VideoChat3 §3.2](https://arxiv.org/html/2607.14935v2#S3.SS2)、[§3.3](https://arxiv.org/html/2607.14935v2#S3.SS3)。表中以简要方法对照说明迁移边界，完整程序行为以本项目代码为证。

General 与 Academic2M 的相似度主要在质量原则；其“用原标签锁住答案语义”这一核心可靠性来源，在 MP4-only 方案中不存在。Long 在“带时序的局部描述 → 跨段训练问题”上更直接借鉴 LV116K，但也没有复制完整官方生产流程。

### 5.3 LLaVA 在这里提供了什么参考

本项目 caption→QA 的“按任务条件生成、自由构造与示例引导”参考了 LLaVA 发布的 QA 脚本；调度堆、当前模板库、候选信封、本地检查、A7 编排是本项目实现。不能把本项目代码标为直接运行官方 VideoChat3 合成器。

- [LLaVA OE 生成脚本](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/gen_sft_data.py)。
- [LLaVA MCQ 生成脚本](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/gen_sft_data_mc.py)。

这两份官方脚本位于 Hugging Face 数据仓库，并不是 VideoChat3 GitHub 下的文件。当前生产程序也不是把官方脚本不加修改地串起来运行。

## 6. 当前需要保持清楚的局限

| 问题 | 当前事实 | 使用时的正确解释 |
|---|---|---|
| 精确帧数 | native MP4 无实际采样回执 | 记录请求 FPS，实际帧数未知，不能承诺固定帧数 |
| caption 的真实性 | L3 过门禁不代表全部 L1 细节通过 | A7 逐条 QA 视觉核查不能省略 |
| 任务均衡 | 只在分支内倾向少数任务，且有适配度约束 | 软目标，不能保证每视频、每小批均匀 |
| 语言/题型耦合 | Long 两类仅 OE，MCQ 只能来自跨段 QA | 全局配比受视频可用证据与 task 白名单约束 |
| 模板多样性 | 每 task 每语言 8 个表达骨架 | 数量不等于语义多样性，也未做逐模板真实 API 质量验证 |
| 真实运行验证 | 已知这轮在 C_GATE 拒绝，未走 QA 分支 | 当前分类与链路是代码核对结果，不是这轮 QA 产物统计 |
| 数据可靠性 | 无独立人工真值校准、人审暂不安排 | 自动通过率不是答案真实准确率 |
| 训练就绪 | token/processor 仍 pending | 导出仍属于自动审核训练候选 |

本文没有修改 prompt、FPS、候选数或门禁阈值。后续若调整，应另起明确变更并验证，不自动触发已有付费轮次重跑。

## 7. 本项目 GitHub 代码入口索引

| 看什么 | 固定版本代码 |
|---|---|
| 10/30 秒、2 FPS 等终端配方 | [terminal.example.json](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/terminal.example.json) |
| 全片窗口及尾段保护 | [caption_plan.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/caption_plan.py) |
| L1/L2、General/Long 与 A7 编排 | [pipeline.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/pipeline.py) |
| 任务分类及生效题型 | [task_registry.json](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/task_registry.json) |
| 192 条模板原文 | [question_templates.json](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/configs/question_templates.json) |
| 当前实际运行生成 prompt | [generation.system.en.txt](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/prompts/task_scheduler/generation.system.en.txt) |
| task 堆、全局配比与模板选择 | [scheduler.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/scheduler.py) |
| 排序/时间/单选/证据程序检查 | [quality.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/quality.py) |
| A7 的视觉审核 prompt | [audit.txt](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/prompts/runtime/audit.txt) |
| API 媒体请求和采样可观测性 | [provider.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/provider.py) |
| 导出 schema 与统计 | [reporting.py](https://github.com/Tiachi/video-sft-builder/blob/fafd14210dcbea97ea8f097142728ec8363301ee/src/video_sft_builder/reporting.py) |

## 附录：全部 192 条模板原文

以下由本审查基线的 question_templates.json 逐条摘录。每行列出同一 task、同序号的中英文各一条，共 96 行、192 条。表中“生效题型”取 task 白名单交集，未照抄模板中过宽的 OE/MCQ 标注。占位槽位保留原文，使用时必须由有证据的内容替换。


### General 完整模板

| task | 中文 ID | 中文原文 | 英文 ID | 英文原文 | 生效题型 |
|---|---|---|---|---|---|
| scene_description | scene_description.zh.01 | {time_ref}，主要活动发生在怎样的环境中？ | scene_description.en.01 | What kind of setting contains the main activity {time_ref}? | OE / MCQ |
| scene_description | scene_description.zh.02 | 从场景布置看，{time_ref}是什么类型的场所？ | scene_description.en.02 | What visible features characterize the setting {time_ref}? | OE / MCQ |
| scene_description | scene_description.zh.03 | 请概括{time_ref}的主要场景。 | scene_description.en.03 | Describe the main scene {time_ref}. | OE / MCQ |
| scene_description | scene_description.zh.04 | {time_ref}，人物周围有哪些能说明环境的特征？ | scene_description.en.04 | What does the surrounding layout reveal about the setting {time_ref}? | OE / MCQ |
| scene_description | scene_description.zh.05 | 就可见背景而言，{time_ref}的环境有何特点？ | scene_description.en.05 | How would you characterize the visible environment {time_ref}? | OE / MCQ |
| scene_description | scene_description.zh.06 | {time_ref}的场地布置与什么活动有关？ | scene_description.en.06 | What activity does the visible setup support {time_ref}? | OE / MCQ |
| scene_description | scene_description.zh.07 | 如何描述{time_ref}里主要活动所在的空间？ | scene_description.en.07 | Describe the space in which the main activity occurs {time_ref}. | OE / MCQ |
| scene_description | scene_description.zh.08 | 观察{time_ref}，用一句话介绍场景及其显著特征。 | scene_description.en.08 | Give a brief description of the setting and its distinctive features {time_ref}. | OE / MCQ |
| entity_attribute | entity_attribute.zh.01 | {time_ref}，{entity}的{attribute}是什么？ | entity_attribute.en.01 | What is the {attribute} of {entity} {time_ref}? | OE / MCQ |
| entity_attribute | entity_attribute.zh.02 | 请描述{time_ref}中{entity}的{attribute}。 | entity_attribute.en.02 | Describe the {attribute} of {entity} {time_ref}. | OE / MCQ |
| entity_attribute | entity_attribute.zh.03 | 根据画面，{time_ref}的{entity}具有怎样的{attribute}？ | entity_attribute.en.03 | How does {entity} appear in terms of {attribute} {time_ref}? | OE / MCQ |
| entity_attribute | entity_attribute.zh.04 | {time_ref}可以从{entity}看出什么{attribute}特征？ | entity_attribute.en.04 | What visible {attribute} characterizes {entity} {time_ref}? | OE / MCQ |
| entity_attribute | entity_attribute.zh.05 | 画面里的{entity}在{time_ref}呈现什么{attribute}？ | entity_attribute.en.05 | Which {attribute} can be observed on {entity} {time_ref}? | OE / MCQ |
| entity_attribute | entity_attribute.zh.06 | 只考虑可见细节，{time_ref}的{entity}在{attribute}方面有何特点？ | entity_attribute.en.06 | Focusing on visible details, describe {entity} by its {attribute} {time_ref}. | OE / MCQ |
| entity_attribute | entity_attribute.zh.07 | 关于{time_ref}的{entity}，其{attribute}如何？ | entity_attribute.en.07 | How would you specify the {attribute} of {entity} {time_ref}? | OE / MCQ |
| entity_attribute | entity_attribute.zh.08 | 用简短表述说明{time_ref}的{entity}的{attribute}。 | entity_attribute.en.08 | Give a brief description of the {attribute} of {entity} {time_ref}. | OE / MCQ |
| spatial_relation | spatial_relation.zh.01 | {time_ref}，{entity}相对{reference}位于哪里？ | spatial_relation.en.01 | Where is {entity} relative to {reference} {time_ref}? | OE / MCQ |
| spatial_relation | spatial_relation.zh.02 | 以{reference}为参照，{time_ref}的{entity}处在什么位置？ | spatial_relation.en.02 | Using {reference} as a reference, locate {entity} {time_ref}. | OE / MCQ |
| spatial_relation | spatial_relation.zh.03 | {time_ref}，{entity}与{reference}的位置关系怎样？ | spatial_relation.en.03 | What is the spatial relationship between {entity} and {reference} {time_ref}? | OE / MCQ |
| spatial_relation | spatial_relation.zh.04 | 请说明{time_ref}中{entity}和{reference}的空间关系。 | spatial_relation.en.04 | Describe how {entity} is positioned with respect to {reference} {time_ref}. | OE / MCQ |
| spatial_relation | spatial_relation.zh.05 | 观察{time_ref}，如何描述{entity}相对{reference}的位置？ | spatial_relation.en.05 | How would you locate {entity} in relation to {reference} {time_ref}? | OE / MCQ |
| spatial_relation | spatial_relation.zh.06 | {time_ref}的画面中，{entity}摆在{reference}的什么方位？ | spatial_relation.en.06 | What relative position does {entity} occupy with respect to {reference} in the scene {time_ref}? | OE / MCQ |
| spatial_relation | spatial_relation.zh.07 | 就{time_ref}而言，{entity}与{reference}如何相对排列？ | spatial_relation.en.07 | How are {entity} and {reference} arranged relative to one another {time_ref}? | OE / MCQ |
| spatial_relation | spatial_relation.zh.08 | 用一句话说明{time_ref}时{entity}相对于{reference}的方位。 | spatial_relation.en.08 | Briefly state the position of {entity} with respect to {reference} {time_ref}. | OE / MCQ |
| action_description | action_description.zh.01 | {time_ref}，{actor}对{object}进行了什么操作？ | action_description.en.01 | What does {actor} do to {object} {time_ref}? | OE / MCQ |
| action_description | action_description.zh.02 | 请说明{actor}在{time_ref}如何处理{object}。 | action_description.en.02 | Describe how {actor} handles {object} {time_ref}. | OE / MCQ |
| action_description | action_description.zh.03 | {time_ref}能看到{actor}对{object}做了什么？ | action_description.en.03 | What interaction with {object} is visible from {actor} {time_ref}? | OE / MCQ |
| action_description | action_description.zh.04 | 围绕{object}，{actor}在{time_ref}的主要动作是什么？ | action_description.en.04 | What is the main action involving {actor} and {object} {time_ref}? | OE / MCQ |
| action_description | action_description.zh.05 | 描述{time_ref}中{actor}与{object}的交互。 | action_description.en.05 | Describe the interaction between {actor} and {object} {time_ref}. | OE / MCQ |
| action_description | action_description.zh.06 | {actor}在{time_ref}以什么方式操作{object}？ | action_description.en.06 | How does {actor} operate {object} {time_ref}? | OE / MCQ |
| action_description | action_description.zh.07 | 用简短句子概括{time_ref}里{actor}对{object}的动作。 | action_description.en.07 | Briefly summarize the action performed by {actor} on {object} {time_ref}. | OE / MCQ |
| action_description | action_description.zh.08 | 观察{time_ref}，{actor}是怎样使用{object}的？ | action_description.en.08 | How is {object} used by {actor} {time_ref}? | OE / MCQ |
| event_order | event_order.zh.01 | {event_a}与{event_b}，哪一个先发生？ | event_order.en.01 | Which happens first, {event_a} or {event_b}? | OE / MCQ |
| event_order | event_order.zh.02 | 在{event_b}之前，是否已经发生{event_a}？ | event_order.en.02 | Has {event_a} already occurred before {event_b}? | OE / MCQ |
| event_order | event_order.zh.03 | 按视频先后，{event_a}和{event_b}如何排列？ | event_order.en.03 | In what order do {event_a} and {event_b} occur? | OE / MCQ |
| event_order | event_order.zh.04 | 请说明{event_a}相对{event_b}的时间顺序。 | event_order.en.04 | State the temporal order of {event_a} relative to {event_b}. | OE / MCQ |
| event_order | event_order.zh.05 | 先看到{event_a}，还是先看到{event_b}？ | event_order.en.05 | Does the video show {event_a} first or {event_b} first? | OE / MCQ |
| event_order | event_order.zh.06 | 视频如何先后呈现{event_a}与{event_b}？ | event_order.en.06 | How are {event_a} and {event_b} presented in sequence? | OE / MCQ |
| event_order | event_order.zh.07 | 若只比较这两件事，{event_a}和{event_b}的顺序是什么？ | event_order.en.07 | Considering these two events, what is the order of {event_a} and {event_b}? | OE / MCQ |
| event_order | event_order.zh.08 | 用简短表述交代{event_a}与{event_b}的先后。 | event_order.en.08 | Briefly describe which comes earlier: {event_a} or {event_b}. | OE / MCQ |
| state_change | state_change.zh.01 | {time_a}到{time_b}，{entity}的状态发生了什么变化？ | state_change.en.01 | How does the state of {entity} change from {time_a} to {time_b}? | OE / MCQ |
| state_change | state_change.zh.02 | 对比{time_a}和{time_b}，{entity}有何不同？ | state_change.en.02 | What differs about {entity} between {time_a} and {time_b}? | OE / MCQ |
| state_change | state_change.zh.03 | 请说明{entity}从{time_a}到{time_b}的变化。 | state_change.en.03 | Describe the change in {entity} from {time_a} to {time_b}. | OE / MCQ |
| state_change | state_change.zh.04 | {entity}在{time_a}与{time_b}分别呈现什么状态？ | state_change.en.04 | What states does {entity} show at {time_a} and {time_b}? | OE / MCQ |
| state_change | state_change.zh.05 | 观察这两个阶段，{entity}怎样从先前状态变为后来的状态？ | state_change.en.05 | How does {entity} move from its earlier state at {time_a} to its later state at {time_b}? | OE / MCQ |
| state_change | state_change.zh.06 | 到{time_b}时，{entity}相比{time_a}有哪些可见变化？ | state_change.en.06 | What visible changes affect {entity} by {time_b} compared with {time_a}? | OE / MCQ |
| state_change | state_change.zh.07 | 围绕{entity}，描述{time_a}与{time_b}之间的状态差别。 | state_change.en.07 | Describe the state difference of {entity} between {time_a} and {time_b}. | OE / MCQ |
| state_change | state_change.zh.08 | 用前后对照的方式说明{entity}在{time_a}和{time_b}的状态。 | state_change.en.08 | Contrast the state of {entity} at {time_a} with its state at {time_b}. | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.01 | {aspect}在{time_a}和{time_b}有什么不同？ | temporal_comparison.en.01 | How does {aspect} differ between {time_a} and {time_b}? | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.02 | 比较{time_a}与{time_b}的{aspect}。 | temporal_comparison.en.02 | Compare {aspect} at {time_a} with {time_b}. | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.03 | 视频前后如何不同地呈现{aspect}？请参照{time_a}和{time_b}。 | temporal_comparison.en.03 | How is {aspect} presented differently at {time_a} and {time_b}? | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.04 | 就{aspect}而言，{time_b}相比{time_a}有什么区别？ | temporal_comparison.en.04 | Regarding {aspect}, what distinguishes {time_b} from {time_a}? | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.05 | 针对{aspect}，这两个时间段有哪些可见差异：{time_a}与{time_b}？ | temporal_comparison.en.05 | What visible differences in {aspect} appear across {time_a} and {time_b}? | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.06 | 请对照{time_a}和{time_b}，说明{aspect}的差别。 | temporal_comparison.en.06 | Contrast {aspect} in the two periods, {time_a} and {time_b}. | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.07 | 从{time_a}到{time_b}，{aspect}的表现有何不同？ | temporal_comparison.en.07 | What differences in {aspect} are visible from {time_a} to {time_b}? | OE / MCQ |
| temporal_comparison | temporal_comparison.zh.08 | 以{aspect}为比较对象，如何概括{time_a}与{time_b}的不同？ | temporal_comparison.en.08 | How would you summarize the difference in {aspect} between {time_a} and {time_b}? | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.01 | 结合{evidence_a}和{evidence_b}，回答：{relation_query} | multi_fact_composition.en.01 | Using both {evidence_a} and {evidence_b}, answer: {relation_query} | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.02 | 要判断{relation_query}，{evidence_a}与{evidence_b}共同说明了什么？ | multi_fact_composition.en.02 | What do {evidence_a} and {evidence_b} jointly establish about {relation_query}? | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.03 | 同时考虑{evidence_a}与{evidence_b}，应如何回答{relation_query}？ | multi_fact_composition.en.03 | Considering {evidence_a} together with {evidence_b}, how would you answer {relation_query}? | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.04 | 请把{evidence_a}和{evidence_b}联系起来说明：{relation_query} | multi_fact_composition.en.04 | Connect {evidence_a} with {evidence_b} to address: {relation_query} | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.05 | 根据这两处线索——{evidence_a}、{evidence_b}——{relation_query} | multi_fact_composition.en.05 | Based on the two cues, {evidence_a} and {evidence_b}, answer: {relation_query} | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.06 | 关于{relation_query}，请给出兼顾{evidence_a}和{evidence_b}的结论。 | multi_fact_composition.en.06 | Give a conclusion about {relation_query} that accounts for {evidence_a} and {evidence_b}. | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.07 | 将{evidence_a}与{evidence_b}放在一起看，{relation_query} | multi_fact_composition.en.07 | Looking at {evidence_a} and {evidence_b} together, answer: {relation_query} | OE / MCQ |
| multi_fact_composition | multi_fact_composition.zh.08 | 请基于{evidence_a}及{evidence_b}两项必要信息回答{relation_query}。 | multi_fact_composition.en.08 | Use the two necessary observations, {evidence_a} and {evidence_b}, to answer {relation_query}. | OE / MCQ |
| observable_causality | observable_causality.zh.01 | 画面中什么直接造成了{outcome}？ | observable_causality.en.01 | What visible action directly causes {outcome}? | OE / MCQ |
| observable_causality | observable_causality.zh.02 | 哪一个可见动作直接引起{outcome}？ | observable_causality.en.02 | Which observed action brings about {outcome}? | OE / MCQ |
| observable_causality | observable_causality.zh.03 | 从可见的作用过程看，{outcome}是如何发生的？ | observable_causality.en.03 | How does {outcome} occur through the visible interaction? | OE / MCQ |
| observable_causality | observable_causality.zh.04 | 请指出导致{outcome}的直接可见因素。 | observable_causality.en.04 | Identify the directly visible cause of {outcome}. | OE / MCQ |
| observable_causality | observable_causality.zh.05 | 哪一处接触或操作使得{outcome}？ | observable_causality.en.05 | What contact or operation leads directly to {outcome}? | OE / MCQ |
| observable_causality | observable_causality.zh.06 | 依据画面中的作用过程，什么使{outcome}出现？ | observable_causality.en.06 | From the visible mechanism, what makes {outcome} happen? | OE / MCQ |
| observable_causality | observable_causality.zh.07 | {outcome}的直接可见原因是什么？ | observable_causality.en.07 | What is the immediate observable cause of {outcome}? | OE / MCQ |
| observable_causality | observable_causality.zh.08 | 请根据实际作用与结果说明，是什么引发了{outcome}？ | observable_causality.en.08 | Explain which visible interaction produces {outcome}. | OE / MCQ |

### Long 完整模板

| task | 中文 ID | 中文原文 | 英文 ID | 英文原文 | 生效题型 |
|---|---|---|---|---|---|
| cross_segment_qa | cross_segment_qa.zh.01 | 结合{segment_a}与{segment_b}，{relation_query} | cross_segment_qa.en.01 | Using both {segment_a} and {segment_b}, answer: {relation_query} | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.02 | 把{segment_a}和{segment_b}联系起来，如何回答{relation_query}？ | cross_segment_qa.en.02 | Connect {segment_a} with {segment_b} to answer {relation_query}. | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.03 | 这两段证据共同说明了什么：{segment_a}、{segment_b}？请回答{relation_query}。 | cross_segment_qa.en.03 | What do the two segments, {segment_a} and {segment_b}, jointly show about {relation_query}? | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.04 | 对照{segment_a}与{segment_b}，{relation_query} | cross_segment_qa.en.04 | Comparing {segment_a} with {segment_b}, answer: {relation_query} | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.05 | 关于{relation_query}，请同时考虑{segment_a}及{segment_b}。 | cross_segment_qa.en.05 | To address {relation_query}, consider both {segment_a} and {segment_b}. | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.06 | 跨越{segment_a}和{segment_b}的可见信息，{relation_query} | cross_segment_qa.en.06 | Across {segment_a} and {segment_b}, answer: {relation_query} | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.07 | 从{segment_a}到{segment_b}的关联中，如何判断{relation_query}？ | cross_segment_qa.en.07 | How does the connection from {segment_a} to {segment_b} inform {relation_query}? | OE / MCQ |
| cross_segment_qa | cross_segment_qa.zh.08 | 请整合{segment_a}、{segment_b}两处必要线索回答{relation_query}。 | cross_segment_qa.en.08 | Integrate the two necessary cues in {segment_a} and {segment_b} to answer {relation_query}. | OE / MCQ |
| event_timeline | event_timeline.zh.01 | 请按先后概括{scope}的主要事件。 | event_timeline.en.01 | Summarize the main events in {scope} in chronological order. | 仅 OE |
| event_timeline | event_timeline.zh.02 | {scope}依次呈现了哪些关键步骤？ | event_timeline.en.02 | What key steps unfold in sequence within {scope}? | 仅 OE |
| event_timeline | event_timeline.zh.03 | 围绕{scope}，说明事件怎样逐步展开。 | event_timeline.en.03 | Describe how the events in {scope} develop over time. | 仅 OE |
| event_timeline | event_timeline.zh.04 | 按照视频顺序梳理{scope}中的显著事件。 | event_timeline.en.04 | Outline the salient events in {scope} following the video order. | 仅 OE |
| event_timeline | event_timeline.zh.05 | 从开端到结束，{scope}的主要进程是什么？ | event_timeline.en.05 | What is the main progression from beginning to end in {scope}? | 仅 OE |
| event_timeline | event_timeline.zh.06 | 请概括{scope}从开始到结束的事件进程。 | event_timeline.en.06 | Give a concise account of the event progression in {scope}. | 仅 OE |
| event_timeline | event_timeline.zh.07 | {scope}中有哪些关键阶段，它们先后如何衔接？ | event_timeline.en.07 | What key stages appear in {scope}, and how do they follow one another? | 仅 OE |
| event_timeline | event_timeline.zh.08 | 请依视频顺序介绍{scope}的过程与结果。 | event_timeline.en.08 | Describe the process and outcome in {scope} in the order shown. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.01 | 请概括{scope}的主要过程，说明各阶段之间的联系。 | hierarchical_summary.en.01 | Summarize the main process in {scope} and the connections between its stages. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.02 | 如何分阶段总结{scope}中的活动及结果？ | hierarchical_summary.en.02 | How would you summarize the activity and outcome in {scope} by stage? | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.03 | 请对{scope}作整体概述，覆盖开始、中间与结束的主要事件。 | hierarchical_summary.en.03 | Give an overview of {scope}, covering the main events at the beginning, middle, and end. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.04 | 围绕{scope}，概括主要活动、实际过程与可见结果。 | hierarchical_summary.en.04 | Summarize the visible activity, process, and outcome in {scope}. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.05 | 请梳理{scope}的整体结构和关键阶段。 | hierarchical_summary.en.05 | Outline the overall structure and key phases of {scope}. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.06 | 用简洁概述说明{scope}如何展开并收尾。 | hierarchical_summary.en.06 | Briefly explain how {scope} develops and concludes. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.07 | 将{scope}中的主要阶段组织成一段完整概述。 | hierarchical_summary.en.07 | Organize the main stages of {scope} into a coherent overview. | 仅 OE |
| hierarchical_summary | hierarchical_summary.zh.08 | 请总结{scope}的全局进程，并交代各主要部分的作用。 | hierarchical_summary.en.08 | Summarize the overall progression of {scope} and the role of its major parts. | 仅 OE |
