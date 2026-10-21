# v0.2 终端与接口验证记录

日期：2026-10-21。实现入口见[终端速查](terminal_quickstart.md)和[接口设计](terminal_ui_and_api_design_2026-10-21.md)。本轮未读取用户真实MP4、未调用云模型、未连接用户GPU/vLLM服务，实际模型费用为0。

## 已执行

| 检查 | 结果 | 范围 |
|---|---|---|
| 设计合同验证 | PASS | General2+3/Long1+2、12字段、CoT独立、拒绝不补题等保持 |
| 完整unittest | 79项：78通过、1跳过、0失败 | 最终冻结代码回归78.222秒；含原测试、18个终端/接口测试及新增A7容量前检 |
| 编译检查 | PASS | src、tests的compileall |
| 本机PTY交互 | PASS | 启动、面板、`/models`、`/help`、`/quit`，进程正常退出；没有启动GPU或调用模型 |
| 非TTY完整界面流程 | PASS | `/output`→`/demo terminal_release`→`/run`→`/status`→`/quit`；无ANSI污染，16条候选、44次模拟推理记录 |
| v0.2 wheel | PASS | 33个包内文件；新增界面/配置/来源/目录模块及两个配置资源完整 |
| 真实FFmpeg测试 | SKIP | 本机无FFmpeg/ffprobe；仍保留仅用程序生成testsrc的可选集成测试 |
| 真实云API/vLLM GPU推理 | 未执行 | 不把localhost协议测试标为真实模型能力/吞吐/质量验证 |

## 新增测试覆盖

1. 私有配置Key保存与重新读取，脱敏显示，POSIX文件600权限；Key不出现在RuntimeConfig repr、冻结JSON或构建目录文件中。
2. Key轮换不改变非秘密请求指纹；默认激活模型修改不改变已有轮次路由。
3. 用户名称+指定日期分钟组成目录，支持汉字；同名碰撞不覆盖，目录穿越/控制字符拒绝。
4. 单个MP4用allowlist，只处理该文件，不复制或改写原片。
5. DeepSeek默认不能派到视频角色；显式Qwen视频+DeepSeek文本/图像混合路由能编译。
6. vLLM未确认采样、未替换served model占位时拦截。
7. 真正启动localhost HTTP服务测试vLLM POST路径、video_url/data URI、全片max_duration、fps/num_frames、JSON响应；不混入Qwen参数或OSS头。
8. vLLM共享file URI路径映射、根目录越界拒绝。
9. DeepSeek使用max_tokens和显式禁用思考；直接video_url调用在本地拒绝。
10. per-role费率入账及同一请求重用缓存，localhost实际只收到一次POST。
11. 直接MP4 URL有字节边界、缓存及SHA256，下载收据去签名query；越界不发布最终文件，默认拒绝HTTP。
12. 界面命令持久化、Key不出现在输出、无ANSI纯文本显示；配置校验失败不覆盖有效私有文件。
13. GET /models只做显式连通/模型ID查询，无POST推理。
14. 包含式v2完整模拟、同目录恢复零额外请求，状态/产物都在命名目录内，不能经正式run误用为真实数据。
15. UI与JSON CLI使用同一轮次锁，第二协调者拒绝进入。

原有预算不足拦截、超时不重发、usage缺失保留预约、超预算中止、A7质量失败不补产、caption拒绝后QA=0等回归测试继续通过。

新增A7整片容量测试：原片已知超过接口文件限制时，在任何caption调用前blocked；本地manifest保留，模型请求数为0。帧数和base64传输边界也在完整运行开始时检查。

## 持久演示产物（Git外）

```text
C:/Users/Tiachi/Documents/Dataset/x_temp/video-sft-ui-release/
    terminal_v02_final_20261021_1746/
    runtime.json
    build.json
    status.json
    coordinator.lock
    inputs/
    state/state.sqlite3
    artifacts/ exports/ reports/
    terminal.events.jsonl
```

报告`reports/63fcc60defeb500e90fb/`。演示General10+Long6=16个自动通过的模拟候选。首次`/demo`后重复`/run`仍为44个模拟请求；这是恢复和界面验证，不是视频质量测量。模拟token费用只用于算术测试，非真实账单。演示输入是不可播放的JSON伪MP4，绝不能混入训练集。

真实处理会按需产生media/与reject/，本模拟不伪称已做真实裁片。

wheel SHA256：`65a2bca70503f1e98977545a6cc0a6fae5c23b470b654df95b6954a669afcb6b`。包、私有配置、媒体/伪媒体、SQLite、日志均不提交Git。实际部署下一步是在用户服务器填好配置，先`/models ping`与`/run prepare`，再在明确预算内做真实试产；不宣称已完成这一步。

## 索引维护

ignored项目索引由41份MD更新至44份MD，无PDF，新增本轮速查、实现、验证三个文件。已有0条人工摘要保留；扫描不触及外部输入/输出目录。

```text
Completion audit:
- Mode: update
- Files indexed: 44 (MD: 44, PDF: 0)
- Outputs: x_temp/SOURCE_MAP.md, x_temp/source_map.json, x_temp/curated_summaries.json
- Curated summaries preserved: yes (0 entries)
- Diff: 3 added, 0 removed
- Original files touched by index generation: no
- All 7 verify checks passed: yes
```
