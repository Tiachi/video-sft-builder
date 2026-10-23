# C_GATE：仅筛查严重视觉不符

日期：2026-10-23。依据：用户明确要求caption与视频没有严重不符即可，并指出稀疏采样可能误拒绝正确内容。该决定覆盖旧版“关键细节支持不足就拒绝”的C_GATE策略，不改变A7。

## 判定标准

| 稀疏视图与caption的关系 | C_GATE处理 | 记录 |
|---|---|---|
| 主要内容可见且支持 | 放行 | supported，仍不声称全片逐帧核验 |
| 某一动作、标题、细节未被抽到 | 放行 | insufficient，不能假改supported |
| 字幕不可读、身份或时序难确定 | 放行 | insufficient及原因 |
| 衣服颜色、次要物体等局部轻微偏差 | 放行 | minor＋contradicted，保留证据 |
| 同一事件/实体/时间范围，主要场景、主体、活动或核心进程明显相反 | 拒绝，不生成QA | major＋contradicted，须有正面反证frame_ids及evidence_note |
| JSON/字段/枚举无效、反证引用不存在、主要内容检查未完成 | 拒绝并归因协议错误/未完成 | 不把技术问题当作严重内容冲突 |

“没有看到”不能单凭稀疏采样推出“不存在”；别的镜头也不能反驳两个样本之间可能出现的镜头。例如衣服颜色偏差通常不改变主要活动；caption把对应画面的车辆维修整体说成烹饪示范，才可能构成严重不符。严重性取决于是否改变核心内容，不设无依据的百分比阈值，也不把任意细节错误都升成major。

## 最小实现

- [caption_gate.txt](../prompts/runtime/caption_gate.txt)：改为major mismatch screen，定义severity、反证与稀疏未知，要求无major反证时模型返回pass。
- [quality.py](../src/video_sft_builder/quality.py)：validate_gate验证协议后，仅以major＋contradicted作为内容拒绝条件；insufficient/minor放行。contradicted必须有既有帧引用及非空说明。模型顶层decision仍保存，但不能覆盖结构化证据：错误的pass不能掩盖major反证，单纯uncertain/reject不能把未知变成反证。
- [pipeline.py](../src/video_sft_builder/pipeline.py)：caption_gate记录policy=`major_visual_mismatch_only_v1`、unverified_claims、minor_mismatches及原始response。模型响应不回写为伪造的全supported。
- [reporting.py](../src/video_sft_builder/reporting.py)：summary.json提供caption_gate_policy及caption_gate_reviews，区分粗筛放行与事实核真。
- report.md同时显示粗筛含义及各视频未核实项/轻微冲突数，避免只看到pass误以为已全面核验。

模型claim新增severity=major/minor；contradicted需要evidence_note。保留critical_claims_complete字段，其含义是“主要内容筛查已完成”，不表示每条事实均有稀疏帧支持。合法非空claim列表可以全部为insufficient，此时也允许通过粗筛；协议不合法仍不通过。

原始模型decision与程序gate decision可能不同，均可审计。原始响应在已完成请求及caption_gate.response保留；新的gate决策只适用于新代码指纹对应的运行，不重新解释历史输出。

## 其他边界

C_GATE仍是每视频一次稀疏视觉调用，帧数、采样公式、分辨率、预算与L1/L2/L3生成方式不变；不补看、不改caption、不增加API。通过后General/Long/Knowledge按原方案生成候选。

这里“不增加API”指没有新增角色/轮次或提高每视频调用上限。原来因稀疏未知被挡下的视频现在可以进入QA，会实际消耗后续文本生成和A7费用；整批账单可能因此增加，仍受已有预算与候选上限约束，不承诺总费用不变。

A7继续每条一次原片完整视觉＋文本：必要事实、答案、任务能力、专业规则等有fail/insufficient仍拒绝，不因C_GATE放行而默认caption正确。最终12字段与cot=null不变，审计元数据在外部。完整caption覆盖、容量blocked和未决付费请求保护仍生效。

## 依据、替代和风险

决定属于用户指定的工程口径。直接依据是旧prompt要求all critical claims supported、旧validate_gate对任意insufficient拒绝；这与当前稀疏视图的有限覆盖不匹配。未采到的信息不能由该视图证伪，是观察范围的逻辑限制，不是已测得的误拒率。没有新增论文性能或真实质量结论。

替代方案是增加抽帧或重看，但这会增加成本并改变已确认的单次调用合同，本次不采用。新口径可能放过未被稀疏视图发现的错误；由逐题A7继续核实必要事实。模型对major/minor和“正面反证”的判定仍可能出错，程序无法独立证明其语义，真实漏拒率/误拒率尚未知。如果后续出现大量major错误通过且A7也接受，应按真实证据重新评估门禁，而不是因通过率高就认为质量提高。

## 使用与旧轮次

只需更新代码；不需要新API或私有配置字段。先等当前运行结束，服务器执行：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
bash scripts/git/sync_pull_ff_only.sh && bash scripts/run_pipeline.sh
```

之后新建的benchmark_v1或legacy_v1运行都使用该C_GATE策略。已有已付费运行不改指纹、不自动覆盖gate、不盲目重发。若要复用旧caption而按新gate重审，应沿既有显式caption-only recovery流程另行操作；本次没有执行该恢复或真实试跑。

本地验证：局部6项测试通过，覆盖major/minor/insufficient与顶层decision冲突、非法协议、未知通过后QA正常生成且仅一次gate、A7证据不足仍拒绝。完整回归结果见本文件末尾的最终验证记录；真实模型效果和服务器部署未验证。

最终验证：全套206项，204通过、2项真实FFmpeg环境相关跳过（165.628秒）；随后补充人读报告的粗筛含义与未核实项显示，并重复局部6项回归通过。测试为合成媒体/模型和localhost协议，未调用真实模型。Git差异空白检查通过；服务器未同步或试跑，真实误拒率和漏拒率未知。
