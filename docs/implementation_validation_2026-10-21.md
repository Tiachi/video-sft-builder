# v0.1 实现与验证记录

日期：2026-10-21。当前结论：四模块、恢复/费用防线、候选导出及报告已实现，并以模拟数据离线验证；没有真实教师API调用，没有处理用户MP4，没有GLM训练或服务器运行证据。本文件不把模拟通过率当作数据正确率。

## 1. 测试结果

环境：Windows，Python 3.12；Python实际版本以运行输出的execution_provenance.json为准。目标执行环境仍为Linux，真实FFmpeg测试当前明确跳过。

| 检查 | 结果 | 证据/范围 |
|---|---|---|
| 设计合同验证脚本 | PASS | General5/Long3、合格全保留、17任务含12启用候选、192模板、CoT独立 |
| unittest全部60项 | 59通过，1跳过，0失败 | 16设计 + 28运行 + 7 Git同步 + 9调度合同；最终整套耗时66.921秒 |
| Bash语法检查 | PASS | run_pipeline.sh、test_all.sh；未冒称Linux服务器运行 |
| Python compileall | PASS | src与tests |
| wheel构建 | PASS | --no-index、--no-deps、--no-build-isolation，本地setuptools构建；27个包内文件 |
| wheel资源核对 | PASS | 控制台入口、task注册、模板、运行配置、生成/审核/caption prompt都在包中 |
| 完整CLI模拟+相同配置重跑 | PASS | 同一导出/报告版本、16条候选；44次模拟推理记录，无额外推理 |
| 原始媒体/真实模型/GLM processor | 未运行 | 缺真实配置和本机FFmpeg，不用mock替代此结论 |

首次在受限Windows沙箱内执行时，Git Bash/本地Git子进程因NtCreateDirectoryObject权限失败，6个同步测试未能启动；正常进程权限下针对同步测试7/7通过，之后最终整套60项通过/跳过如上。没有将这类环境失败改成假PASS，也没有修改同步脚本绕过安全检查。临时测试目录只含本轮创建的可丢弃fixture；Git测试的远程是本地bare仓库，未联系GitHub。

可复现命令：

```bash
bash scripts/test_all.sh
```

可选真实媒体测试为 `test_real_ffmpeg_derived_clip_and_original_immutability`，仅当FFmpeg/ffprobe存在才运行；用程序生成4秒testsrc，检查裁片和原输入字节不变，完全不读取用户视频。当前skip原因：Real FFmpeg/ffprobe are not installed on this host。

## 2. 已覆盖的关键故障路径

- C_GATE拒绝/证据不足：无General、Long或A7调用，caption进reject。
- A7拒绝：16个模拟候选全部拒绝时，生成请求数不增加、不补题；被拒计数从task/比例有效供给中扣除。
- 本地空QA：消耗已产槽、保存local reject、不为它支付A7。
- 明确未产QA弃答：有限尝试、屏蔽当前不适配task，fit缺额不转入balance。
- 模型超时：unknown_execution保留预约，恢复时0次重发。
- 付费响应已收到、generation_response落盘前中断：复用原请求缓存，完成同样16条，总模拟推理仍44。
- 预算不足、固定FPS帧容量不足：在发送前blocked，不自动降FPS/截视频。
- usage缺失：持有预约、该请求不能重发；观察usage越界：停止整轮，恢复也不再发送。
- 截断响应：缓存且不继续/修复；协议不合法不视作语义弃答。
- 原片身份变化拒绝导出；配置变化拒绝复用同run；原子写入不覆盖。
- 不可变JSON镜像缺失可从SQLite恢复；报告半途失败可补齐剩余文件、核对既有内容和完成清单；完成后篡改报告会报checksum错误。
- 同批不同source分别统计，输入=通过+拒绝+pending；混合不同单位不会伪装同一漏斗分母。
- Long单段证据不能冒充多段必要证据；时间基准为原片绝对时间；排序题由程序打乱、生成唯一排列选项。
- Qwen请求结构、max_completion_tokens、原生video_url、OSS私有策略与缓存、分块上传、授权头仅给指定API，以mock验证；不等于真实服务已接受参数。

## 3. 持久模拟结果

本机外部产物目录：

```text
C:/Users/Tiachi/Documents/Dataset/x_temp/video-sft-runtime-smoke-20261021/
  derived/release-v01/exports/7d45cc3b9f414015a657/
  derived/release-v01/reports/93dea949a7ed2549ecf1/
  state/release-v01/state.sqlite3
```

模拟源是30秒与60秒两个JSON伪MP4，不可播放、不构成训练数据。最终General10条、Long6条，全部12字段，cot=null、token pending、quality auto_pass。snapshot manifest显式synthetic=true和training_release=false。相同命令重跑目录不变。

| 角色 | 模拟调用次数 |
|---|---:|
| A1 | 9 |
| A2 | 3 |
| C_GATE | 2 |
| A3 | 8 |
| A5 | 6 |
| A7 | 16 |
| 合计 | 44 |

模拟usage每次固定1000输入/200输出，按模拟费率账本0.05896元，未决预约为0。**这是算术/账本测试值，实际支付0元，不能用于估算真实视频的费用。** A7请求视图指向完整原片而非切片/图片；第二个L2只指向30–60秒视觉，其累计文字范围仍为0–60秒。

wheel SHA256：`11afb81b7e3178f7dc70c41efad67b1383f91942c34c4d0df97daaeb36903a88`。wheel只在ignored x_temp目录，本轮不提交二进制包、媒体、数据库或完整测试日志。

## 4. 尚待真实环境核验

1. Linux FFmpeg版本、实际裁片帧/时间误差、VFR视频等；当前测试仅验证控制路径及异常封装。
2. 真实教师的模型ID、地域、原生视频容量、fps/resize、上传有效期、thinking与usage；确认费率覆盖适用档位后才打开live边界确认。
3. 小批试产的caption幻觉、必要证据、任务分布、模板重复与A7实际拒绝原因；没有真人误接受率测量。
4. GLM processor/采样/token与监督合同，及训练时能否看见标注所需证据；候选中未知值不虚构。

当前状态对应“已实现+本地合成验证”，不对应“真实数据质量通过”“服务器runtime验证”或“正式GLM训练发布”。

## 5. 项目索引维护审计

创建并更新的是ignored `x_temp/SOURCE_MAP.md`、`source_map.json`、`curated_summaries.json`；不会把扫描清单当作代码实现证据，也不扫描外部MP4/派生目录。由38份原有MD更新为41份MD（新增本实现说明、手册、验证记录），无PDF，已有0条人工摘要保持。

```text
Completion audit:
- Mode: update (initial create in this implementation turn)
- Files indexed: 41 (MD: 41, PDF: 0)
- Outputs: x_temp/SOURCE_MAP.md, x_temp/source_map.json, x_temp/curated_summaries.json
- Curated summaries preserved: yes (0 entries)
- Diff: 3 added, 0 removed
- Original files touched by index generation: no
- All 7 verify checks passed: yes
```
