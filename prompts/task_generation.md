# A3 / A5 任务条件生成合同（草案）

这是项目自建提示接口，不是LLaVA或VideoChat3官方原文。尚未接实际模型，不可当作已验证生产prompt。

2026-10-21：此角色仅生成QA，交给主链路审核/发布，训练记录cot=null；不在本响应中补CoT。CoT以后从已发布QA和原视频单独构造。

输入由程序准备：`video_id, branch, caption_version, ordered_facts, absolute_time_windows, assigned_slots[]`。每槽包含 `slot_id, task, language, question_type, num_options, template_id, template_stem`。只接收已过C_GATE的caption，不在本角色补看视频或补标。

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
  "video_id": "synthetic_video",
  "candidates": [{
    "slot_id": "slot_1",
    "task": "event_order",
    "language": "zh",
    "question_type": "oe",
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
