# v0.1 Linux 运行手册

本手册对应已实现的 Python 管道。正式执行前填好外部配置；这里不提供真实 API Key、媒体目录、生产预算或擅自确定采样参数。完整模块与边界见 [实现说明](implementation_v1_2026-10-21.md)。

## 1. 代码环境与离线检查

代码通过 [server_sync.md](server_sync.md) 的私有 GitHub 仓库同步。服务器 Python>=3.11；媒体运行需要 FFmpeg/ffprobe。以下命令均在干净的仓库根执行，不需要将脚本 source 到交互 shell。

```bash
bash scripts/test_all.sh
```

无需 pip 安装即可通过包装脚本运行，它自动设置 src 路径。也可在自己的虚拟环境 `python3 -m pip install --no-deps -e .` 后用 `video-sft`；不要修改系统 Python。包构建依赖 setuptools>=68，模型 HTTP/SQLite/报表均使用标准库，没有 SDK 隐式重试依赖。

不收费的完整流程演示：

```bash
bash scripts/run_pipeline.sh demo --output-root /absolute/external/video-sft-demo --run-id demo-001
```

将示例绝对路径换为自己有写权限、且在 checkout 外的位置。demo 只创建两个 JSON 形式的假 MP4 与模拟响应，不能播放、不是视频训练数据、不联系任何网络。重复相同命令复用状态；不会再产生模拟模型请求。它不能验证真实采样、模型质量或 GLM 兼容性。

## 2. 配置填写

先生成一个在 checkout 外的配置，例如：

```bash
bash scripts/run_pipeline.sh init-config --output /absolute/external/configs/pilot.local.json
```

不覆盖已有文件；所有未填值保留 null，无法启动生产。`configs/project.example.json` 是旧设计合同，`configs/runtime.example.json` 才是运行配置结构。不要把真实配置提交到 Git。API Key 只从 teacher.key_env 指定的已有环境变量读取，不放在配置里。

| 配置部分 | 必须填写/核对 | 说明 |
|---|---|---|
| run | id、output_root、state_root、max_videos、seed | id同一轮固定；三个路径为绝对路径；state/output/input相互不包含且在代码外 |
| input | root、source、recursive、max_scan_entries | source为来源标识；必须明确是否扫描子目录；枚举到max_videos停止，超过扫描条目上限则blocked |
| input.allowlist | 相对于root的MP4列表，或空数组 | 限定明确的视频范围；不接受越出root的条目；大目录首轮推荐小allowlist |
| input.source_by_prefix | 相对目录/文件路径→source映射，或{} | 可同批混合数据集，最长前缀匹配；未匹配使用input.source；由用户登记而不自动猜 |
| media | ffmpeg/ffprobe、timeout、编码器/preset/crf、裁片时长容差 | 裁片写派生目录；输入保持原分辨率，模型按后续参数resize；不改原片 |
| media检查 | sample_count、sample_width/height、min_width/height、黑像素/黑占比/模糊阈值 | 最多64个小样本、采样尺寸16–256；黑/模糊仅粗筛，阈值要按素材校准 |
| media.perceptual_duplicate_hamming | null或0–64整数 | null为关闭近似去重；SHA256精确去重仍启用。当前采样dHash为简单启发式，大规模O(n²)比较不适合无限量输入 |
| caption | l1_seconds、l2_seconds、gate_frame_count | L2必须为L1整数倍；10/30秒只是此前举例，不自动填入正式配置 |
| teacher | backend、base_url、upload_policy_url、model、key_env、transport | 当前live适配qwen_compatible；base_url需含兼容/v1前缀；transport推荐dashscope_oss，base64仅小文件 |
| teacher上限 | timeout_seconds、provider_max_input_tokens、max_video_bytes、max_payload_bytes、max_response_bytes | 按具体供应商模型/地域上限填写；billing_bounds_verified需确实核对后才设true |
| teacher.roles | A1/A2/C_GATE/A3/A5/A7的全部profile | 各角色独立推理配置，不把L1/L2参数套在A7；无A4/A10 |
| budgets | currency=CNY、max_cost、max_requests、per_video_max_requests、max_aux_requests、max_upload_bytes、input/output_per_million | 数量与金额均为硬限制；费率应覆盖账户适用收费档位，不只填写最低档 |
| generation | general_balance_attempts、long_balance_attempts、templates_per_slot | 正整数且有界；12/5为此前建议而非已冻结配置；templates_per_slot<=8 |
| 固定合同 | automatic_retries=0、cot_enabled=false、refill_rejected=false | 验证器拒绝打开这些开关；配比、任务白名单从已登记资产读取 |

角色 profile 详细约束：

| 角色 | mode / 输入 | 额外配置 | 调用数 |
|---|---|---|---|
| A1 | native_video，每段L1 | fps、max_frames、max_pixels、total_pixels、min_video_seconds、sampling_capability_verified | ceil(D/l1_seconds) |
| A2 | native_video，本轮L2新块+历史文字 | 同上；固定密度，不自动改小 | ceil(D/l2_seconds) |
| C_GATE | ordered_images，L3+全片稀疏帧 | max_frames>=gate_frame_count、max_pixels | 完整caption后最多1 |
| A3 | text，General上下文 | visual_token_reserve=0 | 正常4；最多1+general_balance_attempts |
| A5 | text，Long上下文 | visual_token_reserve=0 | 正常3；最多1+long_balance_attempts |
| A7 | native_video，原始完整MP4+单条QA文本 | 完整视频独立profile；考虑时长/文件大小/采样容量 | 每实际可送审QA最多1，最多8 |

每个角色还必须指定 input_token_limit、visual_token_reserve、context_overhead_tokens、max_completion_tokens、enable_thinking、thinking_budget、temperature。非思考时thinking_budget=null；思考打开必须指定budget。视觉角色 input_token_limit 必须等于已核对的provider_max_input_tokens，以全上限预约避免低估；visual_token_reserve是预检估计，不是精确视觉tokenizer。文本角色可设更低输入上限，超过则blocked。

原生视频 max_frames 是本地拒绝边界，不是向供应商请求“到上限后自动降FPS”。只有确认供应商能保留该配置的采样需求后，才设置 sampling_capability_verified=true；实际帧丢失/resize仍须真实试产核查。帧数、像素、上下文或预算无法容纳时不降采样、不截尾，进入pending/blocked。短尾小于供应商最短视频时长也会blocked，不能静默丢弃。

## 3. 正式运行顺序

以下 `/absolute/external/configs/pilot.local.json` 均需换为同一份实际配置。

```bash
bash scripts/run_pipeline.sh validate-config --config /absolute/external/configs/pilot.local.json
bash scripts/run_pipeline.sh doctor --config /absolute/external/configs/pilot.local.json
bash scripts/run_pipeline.sh plan --config /absolute/external/configs/pilot.local.json
```

- validate-config仅结构校验，不测试Key或网络；doctor仅本地可执行程序版本；plan有界ffprobe，不上传、不调用模型、不计算最终真实费用。plan输出逐视频正常调用数、有限尝试上界、保守预约金额和整轮金额上限。
- 确认来源、范围和预算填写正确后，运行下面一个命令；正式run要求代码Git checkout干净并记录完整SHA，避免服务器直接改代码后开始生产。

```bash
bash scripts/run_pipeline.sh run --config /absolute/external/configs/pilot.local.json
```

也可用同一个run_id分段执行，先检查预清理或caption产物；后续完整run复用这些结果：

```bash
bash scripts/run_pipeline.sh run --config /absolute/external/configs/pilot.local.json --through prepare
bash scripts/run_pipeline.sh run --config /absolute/external/configs/pilot.local.json --through caption
```

prepare不创建模型客户端、不需要API Key；配置本身仍需完整显式填写。caption会调用A1/A2/C_GATE，尚不出QA。

run可能上传派生片段、稀疏帧以及原始完整视频到所选API供应商。D秒视频正常产满8题需 `ceil(D/L1)+ceil(D/L2)+16` 次推理；完整流程有限尝试上界为 `ceil(D/L1)+ceil(D/L2)+11+G_attempts+L_attempts`，预算可更早阻断。授权策略GET和OSS上传另计辅助请求/上传字节；OSS缓存可减少重复上传，**不能减少每题A7的视频推理token费**。未接入供应商Batch折扣或缓存token折扣。

## 4. 恢复与结果查看

同配置、同代码、同run_id，重复run命令即可恢复可安全恢复的部分。不要删除SQLite或修改已生成JSON以“重试”。不要换run_id来掩盖unknown_execution；新run不会继承旧run的付费幂等性。

```bash
bash scripts/run_pipeline.sh report --config /absolute/external/configs/pilot.local.json
bash scripts/run_pipeline.sh export --config /absolute/external/configs/pilot.local.json
```

report/export不调用模型，也不为不存在的run新建空状态。run打印候选与报告目录。查看report.md、review.md以及reject目录；reject只保存标注及理由，原MP4仍在原处。

| 结果/状态 | 含义 | 处理 |
|---|---|---|
| pass / auto_pass | 通过本版自动检查 | 候选JSONL全部保留，未达到人工/GLM训练验收 |
| reject | 清理、caption、局部QA或A7质量失败/不足 | 留reject，不卡原片、不补产、不修答案 |
| pending/blocked | 容量、预算、媒体工具或技术条件不能完成 | 中间产物保存；不算质量拒绝，QA可能尚不存在 |
| reserved | 已预约但未进入模型发送 | 可在预算内恢复上传/发送；仍占预算直到得到明确usage |
| sent/unknown_execution | 模型可能已经执行但没有可确认响应 | 自动停下，不重发；先查供应商账单/请求记录 |
| billing_unknown/budget_breach | usage缺失或超过确认边界 | 不当作可重试的语义弃答；查看账本，勿盲目重跑 |

退出码：0为命令成功；run有pending返回2；配置/未决请求/重大计费错误返回1；中断返回130。质量reject本身不令整轮失败。总额预约是应用侧防线，供应商实际违反其确认的收费上限时，客户端无法撤回已执行的推理；报告会明确记录。

## 5. 当前不能省略的后续验证

首轮只产自动审核候选，不需预先安排人审。正式小批次仍应核对：真实FFmpeg裁片/时间映射、供应商实际视频预处理和usage、JSON协议通过率、各环节拒绝率与task覆盖。GLM的processor、帧采样和监督token合同尚未给出，因此不会把tokens.pending候选宣称为可直接验收的训练成品。CoT另行搭建，不阻塞当前QA链路。
