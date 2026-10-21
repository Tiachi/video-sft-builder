> 当前配置与v1流程以 [decisions.md](decisions.md) 为准；本文中的旧默认值、演示模型/数量或历史方案不覆盖最新用户决定。

# 最终训练 JSON 格式与字段候选表

通用与长视频共用同一套 **12 个顶层字段**，分别存入 `general.jsonl` 和 `long.jsonl`，由 `task.pipeline` 区分。题型暂定只有 **`oe`、`mcq`**；MCQ 全部单选，**A–D 四选一为主，少量 A–C 三选一与 A–F 六选一**，具体占比另写配置。

除这 12 类信息外，三级 caption、事件账本、逐帧记录、详细核验、API/模型/代码版本、去重与 split 等全部外置，通过 `id` 关联；不往训练 JSON 增加额外顶层字段或 metadata。此为当前 GLM 方案的自定义合同，读取器尚未运行验证。

**当前CoT决策（2026-10-21）：** CoT之后单独搭建。当前QA版保留cot字段并填null，可以通过QA自身验收后发布；后续以已发布QA与原视频构造、独立核验CoT，另发布新版本。CoT的子结构/方法/监督策略待定，不改原QA的问题/答案/选项。见[独立链路合同](cot_standalone_pipeline_2026-10-21.md)。

**当前任务白名单：** 下表17个任务名是兼容词表，不代表全部主动构造。本阶段建议启用General9、Long3；实际状态见[任务注册表](../configs/task_registry.json)和[分类适配表](phase_one_task_taxonomy_2026-10-20.md)。最终使用`task.family`，注册表必须同名对应；不新增`category`训练字段。

## 1. 最终 JSON 完整例子

以下为虚构的 **ABCD四选一QA版本** 示例，不是真实生成结果。cot=null表示该版本尚未构造CoT，正式QA版本也允许此值。质量和学生token尚未计算，使用pending/null，所以本示例本身不是已验收发布数据；这一限制不来自CoT缺失。MCQ最终答案只写单字母，OE为自然语言答案。

```json
{
  "id": "OwnVideoGeneral_demo001_event_order_mcq_001",
  "source": {
    "dataset": "own_mp4",
    "original_id": "demo001"
  },
  "conversations": [
    {
      "from": "human",
      "value": "<video>\n单选：向杯中倒水后，这个人接着做了什么？\nA. 打开门\nB. 用勺子搅拌杯中的水\nC. 擦桌子\nD. 离开房间"
    },
    {
      "from": "gpt",
      "value": "B"
    }
  ],
  "task": {
    "pipeline": "academic2m_inspired",
    "family": "temporal_understanding",
    "name": "event_order",
    "benchmark_refs": []
  },
  "question_type": {
    "type": "mcq",
    "num_options": 4,
    "options": [
      {
        "id": "A",
        "text": "打开门"
      },
      {
        "id": "B",
        "text": "用勺子搅拌杯中的水"
      },
      {
        "id": "C",
        "text": "擦桌子"
      },
      {
        "id": "D",
        "text": "离开房间"
      }
    ],
    "correct_option_id": "B"
  },
  "media_info": {
    "video_duration_sec": 60.0,
    "video_start_sec": 0.0,
    "video_end_sec": 60.0,
    "caption_sampling": {
      "num_frames": 60,
      "frame_width": 640,
      "frame_height": 360
    },
    "audio_duration_sec": null
  },
  "media": {
    "videos": [
      "videos/OwnVideo/demo001.mp4"
    ],
    "audios": [],
    "images": []
  },
  "modal_mask": 4,
  "quality": {
    "score": null,
    "verify": "pending"
  },
  "cot": null,
  "language": {
    "question": "zh",
    "answer": "zh"
  },
  "tokens": {
    "status": "pending",
    "video": null,
    "audio": 0,
    "image": 0,
    "text_input": null,
    "text_output": null,
    "supervised": null,
    "total": null
  }
}
```

## 2. 字段名称与全部候选值

**粗体列出封闭候选全集；标为“开放”的字段仅给例子。一级/二级任务为本项目当前暂定全集，不表示每个视频都必须生成所有任务。** OE 固定 `num_options=0`、`options=[]`、`correct_option_id=null`；MCQ 选项数只能为 3/4/6，且恰好一个正确答案。JSONL 每行直接保存一个上述对象。

| 对应要求 | 字段名称 | 类型 | 全部候选值 / 开放值示例 | 含义与填写规则 |
|---|---|---|---|---|
| 1. ID | `id` | string | 开放，如 `OwnVideoGeneral_demo001_event_order_mcq_001`、`OwnVideoLong_demo002_cross_segment_001` | 全局唯一的样本 ID；也是外部文件关联键。 |
| 2. 来源 | `source` | object | 固定包含 `dataset`、`original_id` | 原始视频来源，不是合成方法或教师名称。 |
| 2. 来源 | `source.dataset` | string | 开放，如 `own_mp4`、`LLaVA-Video-178K`、`Charades` | 填视频真实来源；自有 MP4 填 `own_mp4`，不要因借鉴 Academic2M 就填成该数据集。 |
| 2. 来源 | `source.original_id` | string | 开放，如 `demo001`、`028CE` | 源视频/源标注 ID；没有时由导入清单分配稳定 ID。 |
| 3. 对话 | `conversations` | array | 对话对象数组，默认一组 `human → gpt` | 实际问题与目标答案；当前单视频，可支持有真实上下文的多轮。 |
| 3. 对话 | `conversations[].from` | string | **`human`、`gpt`** | 只能是这两种角色。 |
| 3. 对话 | `conversations[].value` | string | 开放；问题如 `<video>\n单选：……`，存储的答案如 `B` 或自然语言 | human中写完整问题/选项；gpt.value存最终答案。CoT结构确定后必须与结论一致；监督序列由适配器决定。`<video>`数量须等于视频引用数。 |
| 4. 任务 | `task` | object | 固定包含 `pipeline`、`family`、`name`、`benchmark_refs` | 构造分支、一级/二级能力、benchmark 能力参照分开保存。 |
| 4. 任务 | `task.pipeline` | string | **`academic2m_inspired`、`lv116k_inspired`** | 前者为通用主干，后者为长视频专项。 |
| 4. 任务 | `task.family` | string | **`visual_perception`、`action_understanding`、`temporal_understanding`、`evidence_reasoning`、`long_video_understanding`、`temporal_retrieval`** | 当前暂定一级任务全集，二级任务从下面对应行选择。 |
| 4. 任务 | `task.name`，当 family=`visual_perception` | string | **`scene_description`、`entity_attribute`、`spatial_relation`、`visible_text`** | 场景描述、实体属性、空间关系、可见文字。 |
| 4. 任务 | `task.name`，当 family=`action_understanding` | string | **`action_description`、`fine_grained_motion`、`action_count`** | 动作描述、细粒度运动、动作计数。 |
| 4. 任务 | `task.name`，当 family=`temporal_understanding` | string | **`event_order`、`state_change`、`temporal_comparison`** | 事件顺序、状态变化、前后比较。 |
| 4. 任务 | `task.name`，当 family=`evidence_reasoning` | string | **`observable_causality`、`multi_fact_composition`** | 有可见依据的因果、多个事实组合；不能仅靠时间先后推断因果。 |
| 4. 任务 | `task.name`，当 family=`long_video_understanding` | string | **`cross_segment_qa`、`event_timeline`、`hierarchical_summary`、`recurring_event_aggregation`** | 跨段 QA、事件时间线、层级摘要、重复事件聚合。当前仍用 OE 文本回答或改成单选题，不另设 structured 题型。 |
| 4. 任务 | `task.name`，当 family=`temporal_retrieval` | string | **`segment_retrieval`** | 查询对应的片段检索；当前不把粗窗口冒充精确动作边界。 |
| 4. 任务 | `task.benchmark_refs` | array[string] | 开放，如 `[]`、`["MVBench"]`、`["Video-MME"]`、`["MLVU", "LongVideoBench"]` | 仅为能力体系参照；不是 benchmark 真题来源，没有则 `[]`。 |
| 5. 题型 | `question_type` | object | 固定包含 `type`、`num_options`、`options`、`correct_option_id` | 当前仅 OE 和单选 MCQ，不设置多选/agentic/structured 类型。 |
| 5. 题型 | `question_type.type` | string | **`oe`、`mcq`** | `oe`=开放问答；`mcq`=只有一个正确答案的选择题。 |
| 5. 题型 | `question_type.num_options` | integer | **OE：`0`；MCQ：`3`、`4`、`6`** | MCQ 以 4 选 1 为主，少量 3 选 1、6 选 1；当前不产 2/5/其他选项数。具体占比写外部配置，不另加字段。 |
| 5. 题型 | `question_type.options` | array[object] | OE 固定 `[]`；MCQ 为 3、4 或 6 个选项对象 | 数量必须等于 num_options，顺序与 human 中的选项完全一致。 |
| 5. 题型 | `question_type.options[].id` | string | **3 选 1：`A`、`B`、`C`；4 选 1：`A`、`B`、`C`、`D`；6 选 1：`A`、`B`、`C`、`D`、`E`、`F`** | 按顺序连续编号，不跳号、不重复。 |
| 5. 题型 | `question_type.options[].text` | string | 开放，如 `打开门`、`用勺子搅拌杯中的水` | 选项内容，不包含 `A.` 等标签；标签在 id 中。 |
| 5. 题型 | `question_type.correct_option_id` | string / null | **OE：`null`；3 选 1：`A/B/C`；4 选 1：`A/B/C/D`；6 选 1：`A/B/C/D/E/F`** | 始终是一个值，不是数组。MCQ 必须等于 gpt.value，且该选项是唯一正确项；换位时同步更新。 |
| 6. 媒体参数 | `media_info` | object | 固定包含下列时长、窗口、抽帧字段 | 当前单视频参数摘要；详细取帧/核验/学生视图外置。 |
| 6. 媒体参数 | `media_info.video_duration_sec` | number | 开放，正数，如 `60.0`、`720.0` | 完整原片时长，单位秒。 |
| 6. 媒体参数 | `media_info.video_start_sec` | number | 开放，非负数，如 `0.0`、`120.0` | 使用窗口的原片起点；全片填 0。 |
| 6. 媒体参数 | `media_info.video_end_sec` | number | 开放，如 `60.0`、`180.0` | 原片窗口终点，满足 start < end ≤ duration；建议 `[start,end)`，不自行裁剪原片。读取器须实际支持该窗口。 |
| 6. 媒体参数 | `media_info.caption_sampling` | object | 固定包含 `num_frames`、`frame_width`、`frame_height` | 构造该样本底座 caption 时的实际取帧摘要，不是学生训练取帧配置。 |
| 6. 媒体参数 | `media_info.caption_sampling.num_frames` | integer / null | 开放，如 `60`、`720`；未知 `null` | 该窗口 caption 构造用过的不同帧数；同一帧重复发 API 不重复计数。 |
| 6. 媒体参数 | `media_info.caption_sampling.frame_width` | integer / null | 开放，正整数，如 `640`、`1280`；未知/各帧不统一 `null` | 实际送 caption 教师的统一帧宽，单位像素；不冒充原片宽度。 |
| 6. 媒体参数 | `media_info.caption_sampling.frame_height` | integer / null | 开放，正整数，如 `360`、`720`；未知/各帧不统一 `null` | 同上，为实际帧高；逐帧尺寸在外部保存。 |
| 6. 媒体参数 | `media_info.audio_duration_sec` | number / null | 当前 **`null`**；未来音频任务为正秒数，如 `60.0` | 当前纯视觉不使用音频，不因 MP4 有音轨就填写音频监督时长。 |
| 7. 媒体路径 | `media` | object | 固定包含 `videos`、`audios`、`images` | 媒体相对路径列表；真实媒体根在外部配置。 |
| 7. 媒体路径 | `media.videos` | array[string] | 开放，如 `["videos/OwnVideo/demo001.mp4"]` | 当前恰好一个 MP4 引用；不得写服务器绝对路径。 |
| 7. 媒体路径 | `media.audios` | array[string] | 当前 **`[]`**；未来如 `["audios/OwnData/a001.wav"]` | 当前不使用音频；未来扩展另行适配。 |
| 7. 媒体路径 | `media.images` | array[string] | 当前 **`[]`**；未来如 `["images/OwnData/i001.jpg"]` | 当前不产独立图片样本，教师抽帧不会令此字段非空。 |
| 8. 模态 | `modal_mask` | integer | 当前 **`4`**；预留词表 **`0`=文本、`1`=图像、`2`=音频、`4`=视频、`6`=音视频** | 按当前 GLM 实际消费的逻辑模态定义；本阶段仅纯视觉视频。 |
| 9. 质量 | `quality` | object | 固定包含 `score`、`verify` | 只存最终摘要，详细核验与打分依据外置。 |
| 9. 质量 | `quality.score` | number / null | **0–100**；未知或未校准 `null` | 质量排序分，不是正确率；不能抵消硬性核验失败。 |
| 9. 质量 | `quality.verify` | string | **`pending`、`auto_pass`、`human_pass`、`needs_review`、`reject`** | 待核验、自动通过、人工通过、需复查、拒绝。正式发布不含 pending/needs_review/reject；此处是虚构未核验样例。 |
| 10. CoT | `cot` | null / object | QA版固定null；CoT版为后续确定的已核验object | QA与CoT两版共用12字段；CoT单独构造/发布，原QA不回写，详细状态外置。 |
| 11. 语言 | `language` | object | 固定包含 `question`、`answer` | 问题/选项与回答的主语言。 |
| 11. 语言 | `language.question` | string | 开放，如 `zh`、`en`、`ja`、`ko`；混合 `mul`，未知 `und` | 问题及选项的语言，不是视频来源地区。 |
| 11. 语言 | `language.answer` | string | 开放，如 `zh`、`en`、`ja`、`ko`、`mul`、`und` | OE 为答案语言；MCQ 虽输出字母，沿用题干/选项语言，不把 A–F 标成英文。 |
| 12. Token | `tokens` | object | 固定包含 `status`、`video`、`audio`、`image`、`text_input`、`text_output`、`supervised`、`total` | 目标学生 token 摘要；教师账单和计数方法在外部。 |
| 12. Token | `tokens.status` | string | **`pending`、`estimated`、`measured`** | 未计算、估算、真实目标预处理实测。 |
| 12. Token | `tokens.video` | integer / null | 开放，非负整数，如 `4096`；未知 `null` | 目标学生实际视频视图的视觉 token，不是教师帧数乘一个固定常数。 |
| 12. Token | `tokens.audio` | integer | 当前 **`0`** | 当前不消费音频输入。 |
| 12. Token | `tokens.image` | integer | 当前 **`0`** | 当前没有独立图片输入；视频帧算在 video。 |
| 12. Token | `tokens.text_input` | integer / null | 开放，非负整数，如 `96`；未知 `null` | 按目标 chat template 计算的输入文本 token；媒体占位符不与视觉展开重复计数。 |
| 12. Token | `tokens.text_output` | integer / null | 开放非负整数；未知null | QA版按最终答案目标计；未来CoT版若监督推理，另组序列并重算，不能沿用QA计数。 |
| 12. Token | `tokens.supervised` | integer / null | 开放非负整数；未知null | 真实预处理后labels≠-100的数量；QA/CoT版分别验收，不再叠加到total。 |
| 12. Token | `tokens.total` | integer / null | 开放，非负整数，如 `4224`；未知 `null` | 实际完整序列长度，须与其他计数来自同一冻结的 processor/模板；表中数字仅示例。 |

早期CoT候选参考：[官方生成代码](https://github.com/PKU-YuanGroup/LLaVA-CoT/blob/081cc3fe3670fbff7b30fa22cbcafe031a2077bc/dataset_generation/generate.py)与[历史视频适配分析](llava_cot_video_construction_2026-10-20.md)，均不覆盖当前“方法待定”。原始响应、核验与调用记录外置。
