# Video SFT Builder

从原始 MP4 构造纯视觉视频 SFT 数据：预清理 → LLaVA 三级 caption → General/Long 标注候选 → 综合审核后通过或 reject。

**当前阶段：v0.2新增交互式终端、持久化私有配置、带时间的独立构建目录与Qwen/DeepSeek/vLLM路由；四模块、预算、恢复、reject、12字段候选及报告继续沿用。已完成本地离线/HTTP协议验证，未连接真实云模型或用户GPU服务，没有付费调用。**

2026-10-22修复：完整视频窗口预检、极短尾段合并、caption重复不确定性数组的无损归一化；任何必要产物不完整都显式报未完成，并记录覆盖缺口及非零退出码。旧caption故障轮次可用`/recover 旧目录 名称`新建恢复轮次，精确复用已付费响应。见[完整性与恢复说明](docs/no_silent_truncation_2026-10-22.md)。

## 推荐：终端界面

```bash
bash scripts/run_pipeline.sh
```

首次启动会先检查并自动尝试安装Python>=3.11、FFmpeg/ffprobe，再用程序生成的小视频验证编码和抽帧。已有依赖不重装；安装需要可用的软件源与权限。详见[依赖初始化说明](docs/dependency_initialization_2026-10-22.md)。不需要安装深度学习框架或额外Python运行库。

第一次配置来源、输出父目录和模型Key，之后每轮输入`/new 名称`、`/run`。目录自动为`名称_YYYYMMDD_HHMM`，全部本轮产物（含state）集中其中；Key仅保存在仓库外私有配置，不需每轮粘贴。

见[简洁操作手册](docs/terminal_quickstart.md)、[终端/API实现与vLLM接入](docs/terminal_ui_and_api_design_2026-10-21.md)、[v0.2验证记录](docs/terminal_ui_validation_2026-10-21.md)。DeepSeek配置名为deepseek-v4.1-flash，实际API ID为deepseek-flash；视频阶段需显式路由Qwen或支持视频的vLLM。

## 运行入口

以下保留原JSON命令行入口，见[v0.1运行手册](docs/runtime_runbook.md)；新用户推荐上面的终端界面。工程结构与模块I/O见[实现说明](docs/implementation_v1_2026-10-21.md)，历史证据见[验证记录](docs/implementation_validation_2026-10-21.md)。Python>=3.11，无第三方运行库；真实媒体另需FFmpeg/ffprobe。

```bash
bash scripts/test_all.sh
bash scripts/run_pipeline.sh demo --output-root /absolute/external/video-sft-demo --run-id demo-001
bash scripts/run_pipeline.sh init-config --output /absolute/external/configs/pilot.local.json
```

示例路径须替换为仓库外可写绝对路径。demo全程离线，假MP4与响应只验证流程。填全外部配置后依次执行validate-config、doctor、plan、run；run支持`--through prepare`/`--through caption`分阶段推进。运行配置为[configs/runtime.example.json](configs/runtime.example.json)，null值无法启动正式运行。输出只标自动审核候选，`tokens.status=pending`，不冒充GLM训练验收完成。

## 已确定

- Linux 服务器运行，代码经本公开仓库同步，HTTPS克隆和拉取无需认证。
- 中文/英文 `3:7`，OE/MCQ `7:3`，MCQ 内部三/四/六选一 `1:7:2`；均为最终通过样本条数的全局目标。MCQ始终单选。
- General与Long均启用，二者之间的配比尚未指定。
- 移除A4补标和A10向量/语义分类API。综合审核最多一次，未通过或证据不足直接reject，不回流修复。
- CoT之后单独搭建：已发布QA+原视频→CoT构造/核验→新版本；QA主链路不等待CoT，`cot=null`，方法与监督待定。
- L2只携带本轮新增分块视觉，以历史L2文字＋新增L1文字递推累计摘要；L3之后全片稀疏检查，失败caption reject且不生成QA。此前“每次重送0–t画面”的理解已[纠正](docs/l2_visual_scope_and_cost_correction_2026-10-21.md)。
- General预先5个候选槽位，Long预先3个；通过最终质量检查的全部保留，无额外保留上限或配额裁题。未产QA的明确弃答可有界改派，已产QA不补造。

当前调度方案采用General“适配优先2＋小根堆均衡3”、Long“适配优先1＋小根堆均衡2”；两分支各有task堆，语言/题型取全批次共享缺口。均衡是软目标，不承诺严格等量。详见[评估与完整设计](docs/task_heap_scheduler_evaluation_2026-10-21.md)。

Q2已确认：首轮只产自动审核候选，暂不安排人审；仍产出可阅读统计报告。人审正确率未知，不以自动通过率替代，也不将候选版本视作已验收的GLM训练成品。

Q3已确认：Long不设最低原片时长，按多段必要证据判定适配；实际时长与证据跨度继续统计。

Q4已确认：Long的事件时间线、层级全局总结仅OE；跨段QA允许OE/MCQ。调用前过滤不兼容组合，全局OE/MCQ=7:3目标不变。

Q6已确认：L2保持固定抽帧密度，超容量/预算记blocked，不自动降采样或截尾；具体FPS待定。

Q7已确认：首版不留独立验证集，全部先作训练候选；保留原片/同源组血缘，质量门禁不变。

## 待读取的配置

[configs/project.example.json](configs/project.example.json) 是设计阶段模板，**不是运行入口**；实际执行配置请用[configs/runtime.example.json](configs/runtime.example.json)。MP4目录、派生目录、真实API与凭据配置、预算、首轮范围仍待定。前文`qwen3.8-flash`是演示模型，实际接入尚未确定。

“读取范围”只问是否包含子目录：`root/a.mp4`属于本层；`root/sub/b.mp4`属于子目录。当前保留待定，不自动选择。

## 文档

- [A7当前合同：原视频＋对应文本与费用口径](docs/a7_native_video_input_and_cost_2026-10-21.md)（撤回每题256张图片作为当前成本基线；以实际usage或明确token预算情景计价）
- [L1/L2视频输入2FPS：resize与一小时费用重算](docs/qwen38_flash_native_video_2fps_cost_2026-10-21.md)（型号默认max_pixels=655360，推算1056×576；其余假设不变约11.66元，非实测）
- [1小时1080p＋Qwen3.8-Flash分阶段费用估算](docs/qwen38_flash_one_hour_cost_estimate_2026-10-21.md)（明确情景假设；496次，非思考约20元；实际配置与账单未验证）
- [全链路API调用次数、帧量、弃答改派与成本边界](docs/api_call_inventory_and_cost_contract_2026-10-21.md)（L3无新生成；正常产满8题需7次文本生成、最多8次A7；实际采样/费用上限待定）
- [General5/Long3与合格全保留决定](docs/qa_generation_retention_decision_2026-10-21.md)
- [当前决策与配比语义](docs/decisions.md)
- [四模块设计](docs/video_sft_four_module_project_outline_2026-10-20.md)
- [整体方案评估、19项挑战与逐项决策](docs/full_pipeline_critical_evaluation_2026-10-21.md)（评估建议，不覆盖既定配置）
- [Q1补充：审核API官方推理配置](docs/q1_audit_api_inference_profile_evaluation_2026-10-21.md)（用户已澄清指A7；具体配置未冻结，学生发布验收保留）
- [当前堆调度与2＋3设计](docs/task_heap_scheduler_evaluation_2026-10-21.md) / [新阶段中英prompt](prompts/task_scheduler/README.md)
- [旧单批生成详解：输入输出与后处理历史示例](docs/module3_general_long_walkthrough_2026-10-21.md)
- [本阶段32项能力分类与9+3任务建议](docs/phase_one_task_taxonomy_2026-10-20.md)
- [任务均衡与模板](docs/phase_one_balancing_and_templates_2026-10-20.md)
- [General/Long训练数据密度调研](docs/general_long_qa_density_research_2026-10-21.md)（来源分析保留；旧上限提案已被General5/Long3、合格全保留替代）
- [累计视觉、L3门禁与时间](docs/phase_one_caption_and_time_contract_2026-10-20.md)
- [外部统计与发布合同](docs/phase_one_metrics_and_release_2026-10-20.md) / [虚构报告示例](examples/synthetic_run_report.md)
- [本阶段验证记录与实现边界](docs/phase_one_validation_2026-10-20.md)
- [10个MP4演示](docs/video_sft_ten_mp4_qwen38_walkthrough_2026-10-20.md)（假设案例，不是实测/配额）
- [配置清单](docs/video_sft_user_configuration_checklist_2026-10-20.md)
- [后续独立CoT链路](docs/cot_standalone_pipeline_2026-10-21.md)
- [12字段存储合同](docs/video_sft_final_json_format_2026-10-20.md)（CoT子结构与监督仍待定）
- [Linux同步说明](docs/server_sync.md)

## 代码同步

在Linux上选定代码父目录后首次克隆：

```bash
git clone --branch main --single-branch https://github.com/Tiachi/video-sft-builder.git
```

本仓库为Public，HTTPS克隆和拉取无需登录、SSH密钥或token；推送仍需写入权限与认证。此命令仅克隆代码/文档，不处理视频。

进入新目录后，后续更新运行：

```bash
bash scripts/git/sync_pull_ff_only.sh
```

同步脚本只接受正确origin、干净的main分支和快进更新；拒绝dirty、错误仓库、本地领先或分叉。它不会安装依赖、自动stash或执行数据生产。

## 本地验证

```bash
python3 scripts/validate_design.py
python3 -m unittest discover -s tests -v
```

测试包含设计合同、临时Git同步、完整合成管道与预算/超时/拒绝/恢复故障注入；不访问真实GitHub或模型、不读取用户媒体。若主机有FFmpeg/ffprobe，额外运行程序生成testsrc的本地裁片测试，否则明确skip。PASS不代表真实数据质量或训练兼容性已验证。
