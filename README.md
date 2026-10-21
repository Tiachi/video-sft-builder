# Video SFT Builder

从原始 MP4 构造纯视觉视频 SFT 数据：预清理 → LLaVA 三级 caption → General/Long 标注候选 → 综合审核后通过或 reject。

**当前阶段：本阶段调研与四模块设计已落库，附配置、192个中英文模板和离线一致性检查。数据生产管道尚未实现；没有读取用户媒体、调用教师 API 或运行训练。**

## 已确定

- Linux 服务器运行，代码经本私有仓库同步。
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

[configs/project.example.json](configs/project.example.json) 是设计阶段模板，含有待定/null，**不能据此启动付费或数据构造任务**。MP4目录、派生目录、真实API与凭据配置、预算、首轮范围仍待定。前文`qwen3.8-flash`是演示模型，实际接入尚未确定。

“读取范围”只问是否包含子目录：`root/a.mp4`属于本层；`root/sub/b.mp4`属于子目录。当前保留待定，不自动选择。

## 文档

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

私有仓库需要服务器已有GitHub访问权限；不要在命令URL中嵌入token。此命令仅克隆代码/文档，不处理视频。

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

设计检查只读取配置、任务/模板与虚构统计；测试另创建临时Git仓库，用本地bare仓库模拟远程。不访问真实GitHub、不调用模型、不读取真实媒体。PASS不代表真实数据质量或训练兼容性已验证。
