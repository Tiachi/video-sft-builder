# task堆调度的阶段生成prompt

日期：2026-10-21。**四份文本是项目自建新草案，不是官方prompt，未运行模型。** 最新[调度方案](../../docs/task_heap_scheduler_evaluation_2026-10-21.md)取代旧单批General5/Long3出题请求。

| 用途 | 英文完整原文 | 中文翻译 |
|---|---|---|
| 阶段通用system | [generation.system.en.txt](generation.system.en.txt) | [generation.system.zh.txt](generation.system.zh.txt) |
| 阶段通用user | [user.en.txt](user.en.txt) | [user.zh.txt](user.zh.txt) |

General先发一个`phase=fit`、最多2槽位请求，task=null并提供任务白名单；其响应入账后，均衡阶段逐次发`phase=balance`、固定task的单槽请求，最多产生3条。Long建议全部使用balance阶段，最多产生3条。

程序负责堆排序、全局语言/题型/选项缺口、预约与尝试上限；模型不决定调度权重。`task_inapplicable/evidence_exhausted`屏蔽当前video-task，`form_inapplicable`仅屏蔽当前video-task-language-form-options组合。只有没有产出QA的明确弃答允许重新调度，已产QA被拒不回填。

`{{payload_json}}`必须通过正规JSON序列化替换。英文/中文选一套发送，不同时堆入；输出语言由slot指定。第一阶段的template_candidates按允许task/已分配语言提供少量匹配模板，不把192模板全塞入请求。

这些文件只完成提示合同；运行还需要客户端、响应schema校验、原子计数/恢复、预算控制与模块四反馈接线，目前均未实现。
