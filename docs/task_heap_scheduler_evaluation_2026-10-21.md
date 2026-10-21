# task小根堆与General“适配2＋均衡3”、Long“适配1＋均衡2”：评估和设计

日期：2026-10-21。基线：General最多5条、Long最多3条生成候选，最终质量合格全部保留，CoT后续独立。**结论：建议采用，属于可解释的在线启发式；不能承诺最终严格均衡、全局最优或训练收益。** 本文和配置是设计，生产调度器/状态服务/模型适配尚未实现。本轮只做离线合同校验，不调用模型。

## 1. 保留你的核心思路，补上必要边界

| 你的思路 | 本版完善 |
|---|---|
| General与Long各一个task小根堆 | 每分支维护权威计数字典，小根堆只是排序索引；General9任务、Long3任务分别比较 |
| 先选数量最少的task | 默认按“已最终通过＋已生成待审核＋已预约”的有效供给排序；不按尝试次数排序 |
| 选定task后，再选语言/题型 | 语言/题型用**两分支共享的全批次计数**计算比例缺口；MCQ选项数另做条件调度 |
| General先最适配2条 | 一次A3-fit请求，模型在启用白名单内选择task；程序预分配语言/题型约束；最多产生2条 |
| 再均衡调度至少3次 | 目标是均衡阶段最多产生3条；有可调任务和预算时持续尝试。不适配可以换task；任务耗尽/预算停止就少产 |
| 调到不适配就调下一个 | 只针对**尚未产出QA的abstain**。task不适配在当前视频屏蔽；格式不适配只屏蔽该组合 |

“2＋3”是**生成候选的阶段额度**，不是最终必须通过的条数。第一阶段只产1条时，第二阶段默认仍最多3条，不偷偷改成4条回填。一个已产出的QA即使随后被本地/视觉审核拒绝，也已消耗它的阶段额度，不补造。

Long按用户最新确认采用**适配优先最多1条＋均衡优先最多2条**，用自己的task堆。先由模型在Long白名单中选最适配task生成，响应入账后再逐次调度均衡；fit不足不转给balance，已产QA审核失败不补造。两阶段都必须满足Long的多段必要证据要求。

## 2. 最重要的限制：为什么不能保证最终等量

按你的“最少task”规则，默认目标为**各分支内task等量**：General每类1/9，Long每类1/3。此前注册表中的5/10/20等非均匀权重是旧建议，不参与本版均匀堆排序。若以后改成非均匀目标，应比较`effective_count / target_weight`，不能继续只比较原始数量。

两个堆不保证General9类与Long3类合并后12类都等量；这还受分支产量、视频适配与未指定的General/Long混合影响。本版“全局task均衡”明确解释为**本批次每个分支内部均衡**，语言/题型则对整批合并记录统计。

固定2＋3存在一个供给约束。假设所有视频每次都产生并通过5条，前2条全是action_description，那么动作题占比至少2/5=40%；即使后3条永远不选动作，也无法达到General等量目标1/9≈11.1%。这不是小根堆实现错误，而是自由阶段已经超供给。

一般地，适配阶段在最终合格数据中的占比为α，该阶段task分布为f，均衡阶段为g，总分布为`p=αf+(1-α)g`。要精确实现目标p，至少需要每类`α*f_t <= p_t`；否则所需g会出现负数。实际α受弃答/审核影响，不必等于2/5。

因此默认保留用户的2＋3结构，task均衡作为**软目标**；报告两个阶段各自的通过分布与无法补平的超供给。若长期偏差明显，再研究“适配阶段同等适配时偏向欠缺task”“适配2改1”等备选，不自动改变2＋3、不丢掉已合格题。

## 3. 计数与小根堆：不能只维护一个整数

外部批次状态建议如下，不能放进最终训练JSON：

```text
BatchState
  general.tasks[task] -> Counters
  long.tasks[task]    -> Counters
  global.language[zh/en] -> Counters
  global.question_type[oe/mcq] -> Counters
  global.mcq_options[3/4/6] -> Counters
  general.heap / long.heap -> (effective_count, last_selected_seq, task, version)
  fit_reservations[request_id, slot_id] -> language/form，task暂未知
  video_state[video_id] -> 阶段额度、失败task、失败组合、尝试数、已产QA/证据签名

Counters
  passed                 # 最终质量通过
  pending_generated      # 已产出、尚未得到最终审核结论
  reserved               # 已预约待生成，防并发重复派同一缺口
  generated_total        # 累计实际产出，单独用于报告
  rejected_total / abstained_total / attempts_total
```

堆排序键为`E_t=passed_t+pending_generated_t+reserved_t`；其余累计量不混入E。比如task A已过2、待审10、已预约3，有效供给15；task B已过9、无待审/预约，有效供给9，应先选B。只看已通过数会误派A，只看累计生成数则无法弥补低通过率task。

状态迁移：

| 事件 | 计数变化 | 是否再生成 |
|---|---|---|
| 预约固定task候选 | reserved＋1，立即更新堆；全局语言/题型/选项预约同步 | 发本次请求 |
| 真正产出QA | reserved−1，pending_generated＋1，generated_total＋1 | 该阶段额度已消耗 |
| 模型明确abstain、没有QA | reserved−1，abstained_total＋1 | 可按本设计尝试下一个task/组合 |
| 最终质量通过 | pending_generated−1，passed＋1；有效供给不变 | 全部保留 |
| 质量拒绝 | pending_generated−1，rejected_total＋1 | 仅影响未来调度；不回填被拒的本视频额度 |
| API/解析失败 | 技术状态单记，不能当作task不适配 | 默认停止当前生成链的继续尝试；不循环换task打API |

第一阶段task由模型选择，不能在请求前假装知道它属于哪类。先预约语言/题型/选项，在分支中记录`fit_pending_unknown_task`；响应后把实际task提交为pending。**本视频的适配响应先入账，再开始它的均衡阶段。** 并发其他视频中未知task的fit请求暂不能计入某一task堆，属于短暂统计滞后；应限制并发未决fit请求并报告，不能宣称完全精确。

要让最终通过反馈影响**同一批次后续生成**，模块三与模块四需流水衔接或微批交替。如果整批模块三全部结束后才跑模块四，则本批生成时只能依据待审计数，无法用稍后的通过/拒绝结果追溯调整已完成的生成。推荐流水/微批作为反馈接口，微批大小与并发上限待吞吐/预算确定；不是宣称当前已实现异步系统。

堆节点不能原地改优先级后继续使用。采用版本化新节点＋弹出过期节点，或在任务仅9/3类时从权威字典重建堆。后者简单且开销很小。同分按上次选择序号轮转，再用固定seed/任务名决胜，避免总由字典序决定。

## 4. 语言、题型与3/4/6选项怎么选

task选定以后，对全局语言与题型分别算一步缺口：

```text
E_c = passed_c + pending_generated_c + reserved_c
N   = sum(E_c)
deficit(c) = target_ratio(c) * (N + 1) - E_c
choose c with largest deficit among allowed values
```

语言目标zh/en=0.3/0.7，题型OE/MCQ=0.7/0.3；当选择MCQ时，再以**MCQ子集**为分母调度3/4/6=0.1/0.7/0.2。选完就原子预约，不能等模型返回才计入，否则并发worker会一齐选择同一类别。

示例：语言有效数zh=30、en=121，总数151，下一条缺口为zh=15.6、en=−14.6，应选中文；题型OE=126、MCQ=25，缺口为OE=−19.6、MCQ=20.6，应选MCQ；MCQ内3/4/6数为4/18/3，下一条缺口−1.4/0.2/2.2，应选6选1。这些只决定生成计划，不保证该task一定造得出6个高质量选项。

若格式不适配，要与task不适配区分：不能因为6选1造不出来就宣称这个视频不支持该task。可屏蔽当前`(task, language, type, option_count)`，在同task的其余合法格式中再选择；若明确task本身不适配，则本视频屏蔽整个task。所有重选都受第6节预算与去重条件约束，不能重复尝试同一个已弃答组合。

这些是全局**边际目标**，不要求每个task内部都zh/en=3:7或OE/MCQ=7:3；也不要求每个三元组等量。语言/题型的独立贪心只有在对应组合都可行时才容易逼近目标，不具备全局最优保证。最终通过率不同还会使比例漂移，必须报告实际通过分布。

## 5. 第一阶段：General最多2条、Long最多1条适配优先

Q4已确认兼容矩阵：event_timeline/hierarchical_summary仅OE；cross_segment_qa可OE/MCQ。balance必须在task合法题型内调度，不能因全局MCQ缺口把时间线/总结设为MCQ。fit沿用预分配题型，因此Long的MCQ fit仅从cross_segment_qa选择，OE fit可选三个task；“最适配”是在槽位约束内最适配。模板支持集还须与任务支持集取交集。已知不兼容是本地配置错误，不是模型语义弃答，不发请求。

1. 程序以全局缺口为General最多2个或Long最多1个fit槽位分配语言、题型、MCQ选项数，先做预约。
2. 一次A3-fit（General）或A5-fit（Long）请求读取已有三级caption、所属分支任务白名单与槽位约束，模型选择最适配task及问题。General尽量不同task/事实，Long仍要求多段必要证据；不为多样性强行编题，不足则abstain。
3. 返回task、问题/答案、证据引用；不返回“已经核实”的声明。模型的“最适配”只是生成判断，不是已校准质量分。
4. 先保存响应，再把实际task和当前阶段的计数提交；General最多2个、Long最多1个实际QA进入待审队列。
5. 本视频、本分支的适配阶段完成后再做均衡阶段。未产出的fit额度不回填、不转给balance；Long fit为0时仍可尝试最多2个balance QA。

**无需单独的task适配API**：选task与生成QA在同一请求内完成，不增加A4/A10，也不加视觉补标。语言/题型先固定只是为了不让自由阶段完全破坏全局配方；task仍由模型在白名单中选择。

## 6. 均衡阶段：General争取3条、Long争取2条，不无限循环

```python
K = 3 if branch == "general" else 2
emitted = 0
while emitted < K:
    if no_eligible_tasks_or_budget_exhausted():
        break
    plan = atomic_choose_task_then_marginals_and_reserve(branch_heap,
                                                        video_task_mask, blocked_combinations)
    if plan is None:                    # 无合法task/格式组合
        break
    task, language, form, option_count = plan
    response = generate_one_candidate(task, language, form, option_count,
                                      captions, already_emitted_questions_and_evidence)
    if response.is_candidate:
        commit_generated_candidate_and_pending_counts(response)
        emitted += 1                   # 消耗一个生成额度，不等待它是否过审
    elif response.reason in ["task_inapplicable", "evidence_exhausted"]:
        release_reservation()
        block_task_for_this_video(task)  # 不是从全批次永久删除这个task
    elif response.reason == "form_inapplicable":
        release_reservation()
        block_combination_for_this_video(task, language, form, option_count)
    else:
        record_technical_or_protocol_failure_and_stop()
```

同一task成功后可以重新入堆，但下一题必须有不同所求/必要证据；不是同题换说法。程序本地发现重复或QA后续审核失败时，都按质量规则记录，**不能将已产QA倒改成abstain再腾出额度**。

选择task、选择语言/格式与全部预约在同一协调事务中完成；如果某task的可选格式均已被当前视频屏蔽，就临时跳过它，不留下悬空预约，也不把它误报为全局task不适配。

停止条件：均衡阶段General已产3个或Long已产2个QA；可用task/组合耗尽；调用/费用/上下文预算到达；或技术/协议失败。建议v1再设每视频均衡逻辑尝试上限`启用task数T＋目标生成额度K`，即General最多12、Long最多5次尝试。它是便于控制成本的**项目工程初值**，不是论文最优结论，也不保证能遍历全部语言/题型组合。预算提前停止要记`attempt_budget_exhausted`，不能记成“所有task不适配”。

仅靠task屏蔽且每次abstain排除一个task时，T＋K也是简单保守界；开启格式组合重选后，可能还有未遍历组合而先触发此预算，这一点必须显示在报告里。真实总调用预算仍需运行前明确，不能因设计上限存在而自动运行。

**这是对旧“不补造”规则的精确细化**：允许在QA尚未产生时因明确弃答改选；禁止任何已产QA质量拒绝后的重生成。既有每QA最多一次A7、最终合格全保留、无A4/A10、CoT独立不变。

## 7. API数量与Long边界

General不再是一次批量5条：通常1次fit请求＋3次均衡请求；有弃答则更多。按上面的建议逻辑上限，最多1＋12次生成请求，仍最多产5条QA。Long采用1次fit请求＋最多2次成功均衡请求；均衡有弃答可增加尝试，建议上限为1＋5次生成请求，仍最多产3条QA。每实际QA随后至多一次A7；不能继续沿用旧“一次A3＋一次A5就是全部生成成本”的估算。

上述是逻辑调用，不含未冻结的网络重试策略；建议该调度器生成客户端关闭自动重试，以免上界失真。技术错误不等于语义弃答。最终模型/并发/预算未配置，不启动实际调用。采样、L2新增分块视觉/累计文字、C_GATE成本另计，CoT仍不在这条链路中。

Long仅使用3类启用task，并且必须确实依赖多段证据；模型不能为完成“最少task”而把单帧问题贴成长视频标签。fit最多1个候选的task由模型在白名单内选择；balance最多2个候选的task由堆与证据决定，不强制每类恰好一条。全部最终合格者都保留。Long的1＋2同样是软均衡，不保证最终等量：任务适配与审核通过率仍会造成偏差。

## 8. 状态持久化、并发与统计

堆和计数属于批次状态，每轮新run_id重新开始；恢复同一run_id必须重放已完成事件，不能清零后重做。建议一个协调者负责选堆、预约、释放与最终判定提交，模型请求在锁外执行。多进程不得各有一份互不一致的堆。

每个请求/槽位/sample_id使用幂等键与状态版本；重复返回/审核回调只能计一次。unknown_execution不盲目释放再重发；保留未决状态供恢复。原始媒体只读，所有状态/事件放外部派生根，不提交真实状态数据库或完整日志到Git。

必报：分支task的passed/pending/reserved/attempt/abstain/reject；fit/balance各自贡献；全局语言/题型/选项实际分布与缺口；task不适配与格式不适配分开；每视频尝试数、组合耗尽/预算停原因；未知task的fit预约数；生成调用与候选数；重复/同证据重问率；质量通过分布。

一个task长期稀缺可能是视频供给或caption粒度不支持，而不是调度不够激进。不要为了填平缺口降低质量门禁，或把单视频的屏蔽扩成全局禁用。现有12字段不变，调度历史/堆权重不写进训练JSON。

## 9. 证据、取舍与验证门禁

| 决策 | 依据/状态 | 迁移边界、备选与改变条件 |
|---|---|---|
| 采用2＋3与task堆 | 用户思路；本项目提出工程细化 | 试产前不能宣称提高质量或收益；若适配阶段持续超供给，研究收紧其task偏好，暂不自动改2＋3 |
| 使用小根堆索引 | [Python heapq官方文档](https://docs.python.org/3/library/heapq.html)明确最小项在堆顶及优先级更新问题 | 文档证明数据结构机制，不证明视频QA调度最优；9/3类也可扫描字典，得到相同选择 |
| 指定task、不适配返回空 | [LLaVA-Video §3.3](https://arxiv.org/html/2410.02713v1#S3.SS3)的分任务生成/证据不足不生成 | 原论文不是本堆调度器；不能把None当QA质量通过或重复生成许可 |
| 全局缺口、最终通过反馈 | 本文计数与配比推导，属于proposed | 备选用通过率估计折算pending；v1先不引入未经校准的复杂权重，若延迟/偏差大再研究 |
| 不将均衡称为最优训练调度 | [Graves等ICML2017](https://proceedings.mlr.press/v70/graves17a.html)使用学习进展奖励自适应选任务 | 这是训练课程而非本项目标注调度，不能直接套其算法或增益；本版只是数量启发式 |

离线先检查：堆是否按有效计数选择，预约是否防重复，拒绝/弃答是否正确回退，task/语言/题型/选项分母是否正确，已有QA是否绝不回填，调用上限与幂等是否明确。再用有预算的分层视频试产比较：旧配额调度、纯适配、纯最少task、2＋3；报告每视频/每元新增非重复合格QA、task偏差、全局比例偏差与人审错误。若要称训练更好，还需固定训练token与原视频组的学生对照。

当前只交付设计、配置、完整prompt草案与合同检查，不实现/运行真实调度器。运行前仍缺MP4/API/预算；状态存储、并发协调、响应校验和路由属于后续实现。旧单次批量5条/3条prompt与JSON保留作历史示例，**不能直接当作新两阶段运行入口**。

## 10. 新阶段接口与prompt

完整英文原文与中文译文见[新prompt目录](../prompts/task_scheduler/README.md)，均为本项目草案，未经过模型试产，不是官方原文。一个阶段system配合user模板，按输入phase改变任务选择权。

```json
{
  "request_id": "synthetic_fit_request",
  "video_id": "synthetic_video",
  "branch": "general",
  "phase": "fit",
  "allowed_tasks": [{"name": "event_order", "definition": "Determine supported event order.", "question_types": ["oe", "mcq"]}],
  "assigned_slots": [{"slot_id": "fit_1", "task": null, "language": "en", "question_type": "oe", "num_options": 0}],
  "captions": {},
  "windows": [],
  "template_candidates": [],
  "already_emitted_questions_and_evidence": []
}
```

这是缩短的虚构形状，空caption/windows不能直接发送。实际fit请求General最多两个槽位、Long最多一个槽位，task=null，模型必须从所属分支allowed_tasks选并返回真实task；balance请求只有一个槽位、task明确指定。程序按所选task/语言校验返回template_id及事实引用。

响应继续是`request_id/video_id/facts/candidates/abstained_slots`。新增abstain的封闭reason_code：`task_inapplicable/form_inapplicable/evidence_exhausted`，程序据此决定屏蔽范围。输出候选本身不包含堆、权重、计数或调度意见；新数据仍是12字段QA、cot=null，全部最终合格者保留。

配置入口：[task_scheduler.example.json](../configs/task_scheduler.example.json)；数学/计数虚构例：[task_scheduler_contract.synthetic.json](../examples/task_scheduler_contract.synthetic.json)。这些文件不构成可启动的生产程序。

## 11. 本轮交付与验证状态

| 范围 | 状态与证据 |
|---|---|
| 四模块大纲、调度方案、示例配置、双语阶段prompt | 已文档化；状态均为proposed，不是已实现的数据生产功能 |
| 配置合同与数学示例 | 本次Long1＋2更新后，`python scripts/validate_design.py`通过；9项调度合同/算术测试及16项既有设计测试共25项通过 |
| 完整既有测试回归 | 前版提交318c942中完整31项通过，含本地临时Git仓库同步测试；本次同步辅助脚本未改，只重跑上述相关25项，不将前版31项称作本次全量结果 |
| 既有模块三虚构样例与引用 | 本地只读检查通过：8份JSON、5条12字段待审记录、6份历史内嵌prompt、事实/窗口/模板引用与本地链接；不代表新阶段真实模型输出合格 |
| 生产预约、并发幂等、恢复与审核反馈 | 仅设计，尚未实现；本轮测试没有验证这些运行行为 |
| 实际视频、模型API、候选质量、训练效果 | 未运行、未验证；仍需配置、实现与有预算试产 |

后续实现应优先完成外部权威状态与事件迁移，再接两阶段生成及模块四反馈；不能直接用离线数学示例替代运行时状态机。

本次用户确认更新：Long由“仅均衡3条”的旧建议改为“适配1＋均衡2”；配置、prompt、伪代码与均衡尝试预算已同步调整。新增负向检查禁止恢复旧Long0＋3分配。
