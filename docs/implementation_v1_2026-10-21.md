# Video SFT Builder v0.1 实现说明

更新：2026-10-21。本文记录本轮实际代码；旧调研文档中的“尚未实现”属于当时状态。当前实现为单协调进程、可恢复、有预算约束的候选数据管道，真实 API、真实视频和 GLM 训练验收尚未运行。运行方法见 [runtime_runbook.md](runtime_runbook.md)，测试证据见 [implementation_validation_2026-10-21.md](implementation_validation_2026-10-21.md)。

## 1. 实现范围与来源

| 能力 | 当前状态 | 边界 |
|---|---|---|
| 四模块调度、持久化、断点恢复、预算、reject、报告 | 已实现，合成样例离线验证 | 单协调进程；不承诺多机并发或大规模吞吐 |
| FFmpeg 元信息、抽样检查、裁片、稀疏帧 | 已实现 | 当前机器无 FFmpeg/ffprobe，真实解码集成未验证 |
| Qwen 兼容 HTTP、原生视频、临时 OSS 分块上传 | 已实现，请求结构/缓存/上传以 mock 验证 | 没有付费连通测试；实际 API 及参数仍待用户确定 |
| General 2+3、Long 1+2、task 堆、配比缺口 | 已实现，离线行为验证 | 质量约束优先；不保证最终比例严格满足 |
| GLM processor / 真正训练 token / 学生可见性验收 | 未实现 | 不猜测学生格式与 tokenizer；只导出候选，token=pending |
| CoT、独立验证集、人审、跨分支语义去重 | 不在本轮实现范围 | 遵循已确认决定，不新增付费调用 |

LLaVA 来源为官方数据仓库的[固定版本三级 caption 代码](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py)，revision `6d8c562dc26d70042a0d9704d1cae58c94b89098`，既有本地快照 SHA256 `e5a0ff525a09638f1b4613a346a94705ab243e8c222139e31a98d629a451de50`。其方法用于 L1 局部描述、L2 累计文本；本项目重写了适配器、持久化和质量控制，并按本项目约定在 L2 加入当前新分块视觉。本项目未把该文件直接作为运行依赖。

Academic2M/LV116K 为方法参考；此前未找到可直接复用的完整合成代码。本轮实现是本项目自建的标注协议、prompt 和调度器，不能标为 VideoChat3 官方标注程序。来源与旧评估以既有 [四模块设计](video_sft_four_module_project_outline_2026-10-20.md)、[task 分类](phase_one_task_taxonomy_2026-10-20.md)为准。

## 2. 工程结构

```text
src/video_sft_builder/
  cli.py           # init-config / validate-config / doctor / plan / run / report / export / demo
  config.py        # 严格显式配置、代码与 prompt 指纹
  media.py         # 有界枚举、ffprobe、采样、裁片、原片身份检查
  pipeline.py      # 四模块串联、各阶段状态与拒绝处理
  scheduler.py     # 分支 task 小根堆，全局语言/题型/选项数缺口
  quality.py       # JSON 协议、时间、排序、选项、证据及审核检查
  provider.py      # 单次模型请求、Qwen HTTP、OSS、预算网关
  state.py         # SQLite、不可变产物、请求预约与费用账本
  reporting.py     # 12 字段候选导出、阶段统计、逐题审阅
  synthetic.py     # 隔离的模拟输入与模型；不用于真实生产
configs/runtime.example.json   # 可执行配置的未填壳
configs/task_registry.json     # 9 General + 3 Long 启用候选任务
configs/question_templates.json
prompts/task_scheduler/        # 中英生成协议，原文保留
prompts/runtime/               # L1/L2、L3 gate、A7
scripts/run_pipeline.sh
scripts/test_all.sh
tests/test_runtime.py
```

只有 Python 3.11+ 标准库运行依赖；打包使用 setuptools。真实媒体处理另需 Linux 上的 FFmpeg、ffprobe，编码器按配置提供。代码、MP4、派生目录、SQLite 状态目录分离。状态目录建议本地持久磁盘，不放不支持可靠锁/SQLite 的共享 NFS。

## 3. 四模块输入输出与 API

| 模块 | 输入 | 处理 | 输出 | API |
|---|---|---|---|---|
| 1 预清理 | 显式 MP4 根目录/有界 allowlist、source、阈值 | 有界枚举、SHA256、ffprobe、少量灰度采样；低分辨率/黑屏/模糊/重复拒绝 | 不可变视频 manifest、指标、重复代表关系、prepare reject；原片不改动 | 无 |
| 2 三级 caption | 模块1通过原片 | L1 局部视频；L2 新增块视频+上轮 L2 文字+新增 L1；末次 L2 复用 L3；全片稀疏 gate | 各级文字、窗口/原片时间映射、请求视图、caption_bundle、gate pass/reject | A1、A2、C_GATE |
| 3 QA | gate 通过的全部 L1+末次 L2/L3、窗口、任务/模板 | 分支先适配后均衡；同次输出事实与 QA；绝对时间与单选选项编译；本地质量检查 | candidate、generation_input/response、local reject、dispatch 记录 | A3 General、A5 Long，均文本输入 |
| 4 质量与导出 | 本地检查通过的单条 QA+原始完整视频 | 每题一次综合视觉审核；必要事实/时间/选项一致性检查；合格全保留 | audit reject、General/Long 同结构 JSONL 候选、manifest、报告 | A7，每题原始完整 MP4+文本一次 |

执行采用每视频 caption→General→Long 的流式顺序，在模块3每次实际出题后立即做模块4审核，使审核结果能反馈后续调度；逻辑上仍是四模块。无额外 A4、A10、翻译、事实提取、修复或失败重审 API。

### L1/L2/L3 的精确范围

以 60 秒、L1=10 秒、L2=30 秒为例：A1 六次，A2 两次。第二次 A2 视频仅 30–60 秒；文字可累计覆盖 0–60 秒。L1/L2裁片均从原片派生、不保留音频，不对原片原地转码；模型负责的 resize 由 max_pixels/total_pixels 控制。L3 复用末次 L2，不产生新调用。尾段也保留；若尾段短于供应商视频最短时长，blocked，不丢尾、不擅自重复帧或改采样。

C_GATE 是独立稀疏有序帧视图，含原片绝对时间。失败或证据不足直接 caption reject，QA=0；不能用 A7 替代此前门禁。原生视频供应商的实际帧数/resize 不可观察时，记录请求参数和 `provider_effective_sampling=null`，最终 `caption_sampling` 保持未知。请求 fps 不等于已实测保证帧数；API 的上限/采样行为须在配置确认后用试产观察核查。

### QA 数量、调度与任务

- General：一次 fit 最多2槽，再最多3个实际 balance QA；Long：一次 fit 最多1槽，再最多2个实际 balance QA。fit 未填槽不转给 balance。
- 明确未产 QA 的弃答可在显式次数上限内改派任务/题型；已输出 QA 即占用候选槽。本地/A7 拒绝不回填。正常产满为7次文本生成+最多8次A7。
- 每分支独立 task 堆；有效供给为通过+待审，fit 同批槽临时预约语言/题型。单协调串行调用消除了并行超配问题；平局按最近调度及确定性种子分散。
- 语言/题型/MCQ选项数按全局3:7、7:3、1:7:2缺口选择。先选 task，后与任务/模板白名单求交；时间线、层级总结仅 OE。
- Long 不设置最低视频时长。跨段至少2个不同必要窗口，时间线/总结至少3个；总结要求首中尾覆盖。必要性还须 A7 明确通过；引用多个窗口本身不能证明推理必要性。
- 排序任务可输出 ordering，程序随机呈现事件标签、生成排列干扰项并重映射正确选项；不会把模型输出的事件排序当作人工真值，仍交 A7 一次审核。

L1默认示例10秒意味着窗口级局部事实，短于该粒度的视频可能无法构造多段任务；不会偷偷增加细粒度 OCR/计数流程。`task_registry` 的 proposed_enabled 表示“建议首轮启用、尚待真实数据验证”，不是基准测量结论。

## 4. 费用与断点安全

每次推理先占用请求数和保守金额，再上传/发出。视觉请求使用用户确认的供应商输入 token 上限预约，文本请求使用显式输入上限；输出预约 max_completion_tokens+10，涵盖官方说明的少量超限余量。思考开关和 thinking_budget 显式配置，拒绝隐式重试。预约很保守，并非预期成本。

服务端返回 usage 后按配置单价记账、释放差额；单价必须覆盖本账户适用的输入长度/输出收费档位。`actual_cost` 是“观察到的 usage × 配置费率”，不是已核对的供应商账单；没有实现复杂阶梯账单、缓存折扣、税费、OSS/网络存储费。缺 usage 保留预约并停止该请求链；越过预约直接停止整轮。模型接口无法提供真正的扣费事务，发现供应商违反确认上限时，已发生的超额无法回滚。

请求 ID 包含冻结配置、代码/prompt、视频、阶段及实际输入内容。已完成请求重用响应；发送后超时/进程中断会保留 sent/unknown_execution，续跑拒绝自动重发，防止“已扣费但没收到结果”重复消费。只有上传尚未进入模型发送的 reserved 槽可在上传预算内恢复。未知执行需人工查账，当前没有自动解除或强行重跑命令；更换 run_id 重新跑会产生新的费用。

配置、代码或 prompt 改动必须使用新 run_id；同 run 变更会失败。已完成视频不会再次调用，原片 stat 身份变化会阻止继续/导出。原片 SHA256 在入库计算，续跑为低 IO 的 size+mtime 检查；不能防御刻意保留 size/mtime 的原片修改，仍要求原片存储不可变。

## 5. 导出与外置产物

General 与 Long 采用同一套12字段，只区分 task.pipeline 与 task.name。输出是自动审核候选，`quality.verify=auto_pass`、`quality.score=null`、`cot=null`、`tokens.status=pending`。没有伪造 GLM token、人工质量分、有效采样帧数或独立验证成绩；所有质量通过的记录均导出。

```text
<output_root>/<run_id>/
  resolved_config.json
  code_and_asset_identity.json
  execution_provenance.json        # Git完整SHA、dirty、Python、OS
  media/<video_id>/...             # 仅派生裁片/稀疏帧，不修改原视频
  artifacts/...                   # caption、dispatch、generation、quality、request_view
  reject/prepare|caption|local|audit/<id>.json
  exports/<snapshot_hash>/
    general.jsonl
    long.jsonl
    manifest.json                 # checksum、原片root、候选状态；training_release=false
    README.md
  reports/<snapshot_hash>/
    report.md                     # 来源×环节、逐视频数量/费用
    summary.json
    source_by_stage.csv
    stage_by_source.csv
    stage_events.jsonl
    api_requests.jsonl
    review_index.jsonl
    review.md                     # 逐QA问答/选项/必要窗口/审核；没有声称已人审
<state_root>/<run_id>/state.sqlite3
```

同批多来源可在同一 root 下用 `source_by_prefix` 显式登记各子目录来源，最长路径前缀匹配；这样一个批次内共享堆、比例及账本，报告按 source 汇总。没有自动推断目录名代表哪个数据集。

导出先写唯一 staging，再校验/发布不可变版本；重复导出核对 checksum。数据、响应、数据库、日志均留外部目录，不提交 Git。当前人工审阅率和真实错误接受率未知；下一步是填完整运行配置后，在服务器执行本地媒体检查和明确预算内的小规模真实试产。

## 6. API 适配依据

- [阿里云 Qwen OpenAI 兼容 API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)：视频字段、max_completion_tokens、enable_thinking、thinking_budget。max_completion_tokens 限制思考+回答，官方说明实际可能多最多10 token；实现据此预约余量。
- [阿里云临时文件上传](https://help.aliyun.com/zh/model-studio/get-temporary-file-url/)：授权策略→私有不覆盖 OSS 上传→oss://资源；推理请求设置 X-DashScope-OssResourceResolve，临时URL模型/账户受限。本实现缓存47小时，小于文档48小时有效期。
- [FFmpeg 参数说明](https://ffmpeg.org/ffmpeg.html)、[ffprobe 说明](https://ffmpeg.org/ffprobe.html)：重新编码的准确seek、视频流映射、JSON元信息。代码没有直接复制第三方 SDK 实现。
