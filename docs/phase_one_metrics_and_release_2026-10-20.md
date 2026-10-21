# 本阶段统计、reject 与每轮人审报告合同

更新：2026-10-21。状态：**统计事件合同、合成示例与离线校验已实现；真实生产事件采集/报告生成器未实现。** 文件路径均相对服务器派生根，不能把真实数据写入Git代码仓库。

**Q2当前覆盖规则：** 首轮只产自动审核候选，暂不安排人审。保留方便人阅读的每轮报告与样本定位，不要求这轮实际执行人工核验。报告写human_review_status=not_scheduled、人工核验数量0；人工正确率、错误接受率及置信区间记unknown/null，不填0%错误或100%准确。A7通过率只按自动审核口径报告，不能换名为真实正确率。下文人审抽样要求仅在后续启用人审时适用，不阻塞本轮候选产出；扩量与正式训练发布另行验收。

## 1. 单位先区分，再算保留率

| 阶段 | 主单位 | 必须统计 | 守恒/分母 |
|---|---|---|---|
| 导入/媒体筛选 | video | 输入、通过、reject、pending、路由跳过、重复组 | 对实际处理的视频算；目录中未入allowlist的不算已筛除 |
| L1/L2生成 | caption unit / prefix | 请求、成功、partial、错误、帧数 | 多窗口对一视频，不可直接除以视频数叫通过率 |
| L3 C_GATE | video/caption_bundle | 输入、通过、reject、pending | `input=passed+rejected+pending`；每视频一套bundle |
| QA合成 | candidate slot / QA | 请求槽位、实际生成、abstain、技术缺失、分支任务 | 一对多扩增，不能把QA数减视频数称筛除量 |
| QA本地检查 | QA | 输入、通过、reject、pending | 本地reject不再花A7调用 |
| A7综合审核 | QA | 输入、通过、reject、pending、每类失败、API调用 | 对本地通过者审核；至多一题一请求，错误亦消耗调用 |
| 最终保留 | QA | 合格池、retained、pending；兼容旧selected字段 | 最终合格全保留，因数量/配额的selection_excluded必须0；发布等待单独记pending |
| QA学生处理 | QA / supervised token | 覆盖、溢出、实际QA目标token | 不以教师API usage冒充学生训练token；CoT另轮统计 |

完整轮次同时给“阶段条件保留率”和“从最初视频/QA队列累计保留率”，分母写在列名里。阶段未执行、统计缺失写null/unknown，不能写0通过或100%通过。预算停止、API能力不足导致未启动的对象记pending/blocked，不混成质量失败。

## 2. 外部事件与关联

建议 `audit/stage_events.jsonl` 每条结构：

```json
{
  "run_id": "synthetic_run",
  "event_id": "ev_001",
  "stage": "caption_gate",
  "entity_type": "video",
  "entity_id": "synthetic_video_03",
  "source_id": "synthetic_source_A",
  "video_id": "synthetic_video_03",
  "sample_id": null,
  "decision": "reject",
  "primary_reason": "insufficient_visual_support",
  "additional_reasons": [],
  "input_refs": ["02_caption/captions.jsonl#synthetic_video_03"],
  "request_id": "synthetic_request_03",
  "attempt": 1,
  "recorded_at": "2026-10-20T00:00:00Z"
}
```

这是**虚构说明**。正式事件附版本/commit、配置/提示/模型引用和视图引用；不写密钥、完整鉴权头或可用签名URL。重复执行以 `run_id+stage+entity_id+attempt` 幂等，报告聚合终态而非把每次日志行都算一条被拒数据。实体改写/派生使用新版本，不覆盖旧证据。

主拒绝原因每对象一个，保证主原因计数之和=reject；额外原因可多选，明确总和可能大于reject。技术失败主原因用 `api_error/invalid_response/unknown_execution`，事实错误、答案不唯一、无证据、时间错误等分别登记。C_GATE失败无sample_id，并保证该video的本轮QA=0。

## 3. 必需的两个统计视角

保留基础长表：`source_id, stage, entity_type, input_count, passed, rejected, pending, selection_excluded, primary_reason`。对所有涉及筛选的阶段登记，即使本轮该阶段0条拒绝。

1. **按来源看全链路：** 每数据集/来源在导入→媒体筛选→caption门禁→QA生成→本地→A7→最终保留的数量、分母和原因。
2. **按阶段看来源：** 某阶段每来源输入/拒绝/保留、该来源条件拒绝率、占该阶段所有拒绝的比例。后两种比例不可混淆。

同一MP4可出现在两分支，但视频总数用video_id去重；QA按sample_id计数。多个来源下同一媒体的去重组保留来源血缘，重复输入与最终媒体数分开统计，不能双算全局唯一视频数。

## 4. 每轮报告清单

`reports/<run_id>/report.md` 是人审入口，另导出CSV/JSON汇总与可定位样本索引；报告不要求读者访问整份底层日志。当前手工编写的 [synthetic_run_report.md](../examples/synthetic_run_report.md) 与 [synthetic_run_metrics.json](../examples/synthetic_run_metrics.json) 演示数量关系，**不是运行结果**。

| 部分 | 内容 |
|---|---|
| 轮次身份 | run_id、全commit SHA、配置/提示/教师版本、实际起止、输入allowlist、输出不可变版本、状态/未完成原因 |
| 核心漏斗 | 来源×阶段双视角；视频、caption、槽位、QA、调用独立单位；主/附加原因与条件/累计率 |
| 分布与缺口 | 分支、task、语言、OE/MCQ、MCQ3/4/6、正确字母、来源、时长、分辨率、证据段数；目标/实际/缺口与整数可达性 |
| 分支产量与保留 | General5/Long3请求槽位、实际生成、abstain、质量通过、拒绝、最终保留；合格全保留，无额外数量/配额上限 |
| 多样性 | 模板使用率/集中度、重复问法/答案、单视频贡献、文本近重复与去重组；不宣称语义去重已实现 |
| 时间与视图 | 原片绝对时间校验、精确边界违规、L2范围、L3检查视图、学生证据覆盖、长视频超容量比例 |
| 资源 | 角色调用数/错误/等待、输入输出usage、视频帧/像素、费用币种；估算与真实计费分开；监督token单列 |
| 人审队列 | 分来源/task/分支抽通过、reject、uncertain、历史合格未选；给问题/答案/外部证据/原片片段入口、判断表与抽样种子 |
| 发布结论 | QA候选/QA发布及学生验收状态；CoT未构造不阻塞QA，cot=null |

人审抽样需包括随机层化样本，不能只挑模型最低分或好看的样例；样本量与通过率估计的置信区间需按试产规模选择。本轮不虚构一个经过人审的准确率阈值。

## 5. 外部文件布局与12字段

```text
derived_root/run_id/
  01_prepare/{media_manifest,eligible_videos,media_checks,groups,reject}.jsonl
  02_caption/raw/...
  02_caption/{captions,frame_views,caption_checks,reject}.jsonl
  03_synthesis/{events,evidence,generation,general_candidates,long_candidates}.jsonl
  04_quality/{local_checks,audits,reject,passed_pool}.jsonl
  audit/{stage_events,api_calls,sample_index,student_views}.jsonl
  reports/run_id/{report.md,source_by_stage.csv,stage_by_source.csv,...}
  release_staging/{general,long}.jsonl       # 未完成门禁，不作为release
  release/<immutable_version>/...           # 验证后原子发布/可回滚
```

最终每条仍只有：`id, source, conversations, task, question_type, media_info, media, modal_mask, quality, cot, language, tokens`。详细caption/事实/模板/视图/请求/拒绝/阶段统计/样本选择信息全部外置，通过 `sample_id=id` 与video_id索引关联。`source` 是实际原视频来源，不能因为用了论文方法填成Academic2M或LV116K。

## 6. 发布门禁与验证边界

Q7覆盖规则：首版不留验证集，全部先作训练候选，组级信息仍保留。没有执行的train/validation泄漏检查记not_applicable_this_run，不能伪写PASS或独立验证成绩；这也不证明与未来外部benchmark无重合。后续若开启划分或benchmark评测，再按实际用途启用相应隔离验收，不以本轮未留验证集阻塞候选构造。

QA候选质量通过后还需学生processor/tokenizer/chat template与采样固定、关键证据在训练视图可见、真实序列/监督token与长度验证、原片/同源组血缘及本轮适用的用途检查、12字段和媒体路径有效、报告完整。Q7首版不分验证集，对应划分检查记不适用；若将来启用划分/评测，则启用相应组级隔离检查。满足后可发布QA版本，cot=null，原片只读。后续CoT独立构造/核验并发布新版本；CoT失败不修改原QA，独立报告拒绝率及其造成的分布变化。

本轮 `scripts/validate_design.py` 只检查**设计配置与合成统计的内部一致性**，不读取媒体、不判断答案真伪、不证明真实数据质量、CoT合规或GLM训练兼容。生产发布门禁尚未实现；不能拿本轮PASS代替数据验收。

2026-10-21数量更新：General5槽、Long3槽；最终合格全保留。兼容示例中的qa_selection/selected现表示保留核对，不是数量挑选器；当前selection_excluded必须0。比例按规划/报告控制，不删合格题凑比。
