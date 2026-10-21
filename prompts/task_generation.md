# A3 / A5 任务条件生成合同（草案）

这是项目自建提示接口，不是LLaVA或VideoChat3官方原文。尚未接实际模型，不可当作已验证生产prompt。

2026-10-21：General预排5槽、Long预排3槽，最终合格全部保留，不按数量/配额裁题。此角色仅生成QA，交给主链路审核/发布，训练记录cot=null；不在本响应中补CoT。CoT以后从已发布QA和原视频单独构造。

完整拟用英文prompt与中文译文见[module3/README.md](module3/README.md)，逐步流程/伪代码/完整JSON例见[模块三详解](../docs/module3_general_long_walkthrough_2026-10-21.md)。这些都是新写项目草案，并非VideoChat3官方生产prompt。

输入由程序准备：`request_id, video_id, branch, caption_version, captions, windows, assigned_slots[], demonstrations[]`。每槽包含task定义、语言/题型/选项数及模板。若上游已有结构化事实可复用；只有文字caption时，程序先归档观察/时间索引，由A3/A5在同次出题响应中提取相关facts，不另增事件标注API。只接收已过C_GATE的caption，不在本角色补看视频或补标。

指令：

1. 严格按槽位的能力定义构造。使用已有caption与明确可引用的事实；不把“未提到”改成“未发生”。每题返回必要事实/原片窗口引用。若无法构造，返回该slot的abstain及原因，不改成其他task、不猜答案。
2. 同一次响应完成模板填充与自然改写，保留task与事实，不模板化复制答案。目标语言与程序配方一致。
   问题中的证据/片段槽位只能是定位线索，不得把待求答案的完整事实抄入题干；若仅凭题干/选项即可确定答案，返回abstain。
3. OE使用自然语言答案。绝对时间只引用输入已有的时间锚，不能创造精确边界。MCQ只生成指定3/4/6个选项、单一正确；选项语义同维度且互不等价。程序随后打乱选项并同步字母。
4. Long的问题必须需要多处非重复的视觉证据：跨段关系、事件时间线或层级概述；单段/静态/语言常识可答则abstain。最多按3个预分配槽位返回，不自行追加候选。
5. 生成的证据说明是可审查的事实摘要，不是已核验GT，也不是已选定的CoT。不得在本阶段自行冻结CoT四段结构或监督格式。

输出是内部JSON：

```json
{
  "request_id": "synthetic_request",
  "video_id": "synthetic_video",
  "facts": [
    {"fact_id": "fact_1", "claim": "虚构前一事件", "caption_ids": ["caption_1"], "evidence_window_ids": ["window_1"]},
    {"fact_id": "fact_2", "claim": "虚构后一事件", "caption_ids": ["caption_2"], "evidence_window_ids": ["window_2"]}
  ],
  "candidates": [{
    "slot_id": "slot_1",
    "task": "event_order",
    "language": "zh",
    "question_type": "oe",
    "num_options": 0,
    "question": "示意问题，不是真实标注",
    "answer": "示意答案",
    "options": [],
    "correct_option_id": null,
    "required_fact_ids": ["fact_1", "fact_2"],
    "evidence_window_ids": ["window_1", "window_2"],
    "template_id": "assigned_template_id"
  }],
  "abstained_slots": []
}
```

内部结构不直接进入训练集；最终12字段由组装器构造。A3/A5响应不合格时按配置记录失败，不照搬公开代码的无限错误重跑。
