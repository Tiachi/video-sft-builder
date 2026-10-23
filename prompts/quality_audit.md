# C_GATE 与 A7 审核合同（草案）

两个角色处于不同阶段，不能合并成生成QA后再审caption。它们可以接同一视觉API后端，默认各逻辑对象最多一次请求、SDK retries=0；不做失败后的修复/补看。

## C_GATE：先检查L3，后决定是否允许QA

输入：原片全范围稀疏有序视图、实际绝对时间、L3及其版本。2026-10-23用户指定只筛查严重不符：每条claim保留supported/contradicted/insufficient，并标major/minor；contradicted须给既有frame_ids与非空evidence_note。只有同一实体/事件/时间范围的明确major视觉反证才语义拒绝；缺乏稀疏支持及minor冲突保留记录后放行。不能把insufficient假记supported。模型顶层decision保留，程序根据claims决定是否放行。协议错误或未完成主要内容检查仍不通过。失败对象是video/caption，没有QA；通过只表示没有确认严重不符。生产prompt见[runtime/caption_gate.txt](runtime/caption_gate.txt)，细则见[门禁口径](../docs/caption_gate_major_mismatch_policy_2026-10-23.md)。

## A7：一题一次综合视觉审核

输入：直接传入原始完整视频文件（或其可访问URL），以及审核指令、绝对时间基准、该题的问题/答案/选项、指定task与必要事实引用。每题一次同请求发送视频和对应文本，不将“256张1080p独立图片”作为当前默认输入。API负责视频抽帧/缩放，实际FPS、帧上限、像素与内部思考配置仍需冻结并核验，不能把文件已上传等同于逐帧完整观看。QA主链路不输入或核验CoT，未来CoT使用独立审核。失败后不补发画面或重审；审核应以实际可见画面为依据，caption/候选答案只是待验证内容。

同次检查：

- 问题是否可回答，候选答案是否由可见证据支持，是否增加了看不清的细节。
- MCQ选项数正确、唯一正确、干扰项不等价，答案字母对应正确文本；OE回答是否完整且无额外事实。
- task是否成立：比较是否真需要两处证据，因果是否具有可见作用机制，Long是否真依赖多段而非单帧/单段/常识。
- 实体指代/跨段身份、语言、时间锚、问答一致性。精确时间边界没有依据就拒绝。
- 是否只是重复/模板空话；QA事实、结论及答案必须一致。
- 题干是否通过填入完整证据事实泄露待求答案，是否无需视频即可回答；这类问题拒绝，不因task标签复杂而放行。

输出每项 `pass/fail/insufficient/not_applicable`、引用的实际时间、总decision与唯一primary_reason。总pass要求所有适用硬项pass。fail/uncertain/insufficient/error均不进入通过池；不返回“修改后答案”作为新训练标注。

本地结构/路径/重复/时间上下界错误可在A7前拒绝，减少费用。一次综合请求可以一次完成多项判断，但不能据此承诺审核准确率；人审抽样用于估计误判。
