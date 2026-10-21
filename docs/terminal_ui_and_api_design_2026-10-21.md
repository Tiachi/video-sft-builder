# v0.2 终端界面与API路由实现

用户需求：终端交互式操作、持久化来源/输出/API、由用户提供s并组合开始时间命名、所有轮次产物集中、支持自建vLLM。简明操作入口见[速查手册](terminal_quickstart.md)。本轮不改General2+3、Long1+2、三级caption范围、一次A7、质量拒绝不补题或12字段合同。

## 1. 实现结构与状态

| 部分 | 实现 | 证据边界 |
|---|---|---|
| `terminal.py` | 状态面板、slash命令、Tab补全、ANSI进度/费用、非TTY降级、编辑器、Key隐藏输入 | 本机PTY交互和离线模拟验证；不等于Linux服务器已运行 |
| `settings.py` | 单个私有JSON、三个模型预置、默认激活模型、路由、显式配方、Key脱敏 | 配置持久化、原子写、POSIX600、Key轮换不改变请求身份的测试 |
| `builds.py` | s+分钟时间的唯一目录、新建/恢复、轮次冻结、所有生成物与SQLite集中 | 合成完整链路及无额外调用恢复测试 |
| `sources.py` | 本地目录/单文件allowlist、直接MP4下载、大小/时间边界、缓存、来源指纹 | localhost直链测试；未下载任何用户媒体 |
| `config.py` | schema v2包含式布局、provider能力与角色匹配；保留v1读取 | 不能把无视频能力的模型配置成A1/A2/A7来付费碰运气 |
| `provider.py` | Qwen、DeepSeek、vLLM参数方言与逐角色路由 | 本地HTTP协议测试，不声称真实云端/GPU推理已验证 |
| `state.py` | 回调进度、恢复已有计数、逐角色费率入账 | 计费/未决请求/单协调锁机制继续成立 |

终端只负责配置与呈现，调用既有Pipeline，不另写一套生成算法。进度回调仅含阶段、ID、token/费用，不记录API Key、Authorization或完整付费请求。界面渲染异常不改变账本；网络仍为一次发送、无SDK自动重试。运行中只显示动态状态，不流式拼接半个JSON作训练记录。

## 2. 私有配置与冻结配置分离

`configs/terminal.example.json`是可审阅的空Key模板；`configs/provider_presets.json`记录接口预置。运行时用户私有文件默认`~/.config/video-sft-builder/config.json`，也可用`--settings`或VIDEO_SFT_CONFIG指定，禁止放到代码checkout中。

用户明确授权把Key保存在私有配置，此决定覆盖此前“Key仅环境变量”的建议。只在该私有文件中有api_key；新建轮次的runtime.json、resolved_config.json、SQLite、报告、终端事件均不保存Key。运行中内存凭据字段不参与repr或请求指纹，已有环境变量可备用。Key不作为命令行参数，避免终端历史；界面只显示“已配置/未配置”。

每轮冻结非秘密provider参数、路由、费率、采样、预算、源范围和代码/prompt指纹，并记录共享私有配置的路径。之后的默认模型变更不影响旧轮次；Key轮换从同名profile读取。换Key仍需同一模型/供应商/媒体授权相容，不能把变换API地址伪装成Key轮换。

未填真实Key、vLLM模型名占位、视频能力不足、未声明采样能力时，正式推理会在发送前失败。预清理不需要模型Key；完整运行会先检查本轮全部所需profile的凭据存在，避免先支付caption再发现QA模型没有Key。GET /models是用户显式操作，非自动推理探测。

## 3. 每轮目录和来源

```text
<output_dir>/s_20261021_1651/
  build.json                 # 用户名称、创建时间/时区、来源公开部分及指纹
  runtime.json               # 非秘密、冻结执行配置
  coordinator.lock           # UI和旧CLI共用同一把锁
  status.json
  inputs/                    # 仅远程下载或明确标记的合成演示
  state/state.sqlite3
  media/                     # 派生裁片/稀疏帧
  artifacts/ reject/ exports/ reports/
  terminal.events.jsonl
  resolved_config.json code_and_asset_identity.json execution_provenance.json
```

命名采用本机当地时间到分钟，同时build.json记录ISO时区；同名同分钟不覆盖、不自动偷偷加后缀。名称允许Unicode字母/数字和_.-，禁止目录穿越、控制字符和空格。原本地媒体继续只读，单文件来源只处理该文件，不把同目录其他MP4顺带加入。

远程来源只支持用户给出的MP4直链，可带签名query；私有设置保存原地址，构建产物只保留去query/用户信息的URL及指纹。流式下载到本轮inputs，限字节/超时，成功后SHA256校验，恢复复用下载。HTTPS默认启用；内网HTTP须显式download.allow_http。已有下载可在全局source改动后继续用；尚未下载完时需恢复原来源设置。原子发布中断产生孤立最终文件时拒绝覆盖，需检查，不假装下载成功。

v1的输入/状态/输出三根目录布局仍保留；UI新轮次使用v2包含布局。不自动迁移已有付费状态。旧轮次若代码指纹不匹配，应使用原提交恢复或只读已导出文件，不能新建轮次来掩盖未知扣费。

## 4. 模型能力与请求方言

| Profile | 请求model/输入 | 输出上限/思考开关 | 适用阶段 |
|---|---|---|---|
| qwen3.8-flash | qwen3.8-flash；文本、图像、原生video_url | max_completion_tokens；enable_thinking，显式thinking_budget | 全部；视频内容处携带fps/max_pixels/total_pixels |
| deepseek-v4.1-flash | deepseek-flash；文本、图像 | max_tokens；thinking.type=disabled | A3/A5及图像C_GATE；不接受原生视频阶段 |
| vllm | 用户served model name；按部署声明能力 | 可配max_completion_tokens/max_tokens；默认chat_template_kwargs关闭思考 | 模型支持什么才启用什么；原生视频和多图已实现协议适配 |

DeepSeek原生视频能力没有官方依据，不能仅因其多模态就声称支持video_url。选择DeepSeek做默认后，用户需显式`/route video qwen3.8-flash`或路由到已配置vLLM，程序不暗中fallback。C_GATE可以使用DeepSeek的多图输入，QA仍只读caption文本。A7继续原始完整MP4+单条QA，而非被新界面替换成帧列表。

Qwen保持原有私有OSS上传/缓存及原生视频参数；vLLM/DeepSeek请求不携带Qwen专用字段或OSS授权头。generic adapter暂不启用无法单独约束thinking_budget的思考模式；不能通过extra_body绕过受控输出长度、模型、消息、流式或思考开关。

来源：[Qwen模型说明](https://help.aliyun.com/en/model-studio/qwen3-8-flash)、[Qwen兼容协议](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)、[DeepSeek首次调用](https://api-docs.deepseek.com/quick_start/pricing)、[DeepSeek图像接口](https://api-docs.deepseek.com/guides/vision/)、[DeepSeek Chat参数](https://api-docs.deepseek.com/api/create-chat-completion/)。核对日期2026-10-21；实际账户/地域与版本仍需运行核查。

## 5. vLLM部署接入

最低条件：Chat Completions路径、正确served model name、支持所选模态的模型和chat template、足够上下文/图像数量/视频容量。文本模型只能承担A3/A5；不能用“HTTP返回200”代替视觉能力证明。

- **base64**：媒体随请求发送，适合小片段和小原片；本地/远端vLLM均可。不假定客户端路径就是服务端路径。
- **file_uri**：用于共享文件系统/同服务器，显式配置local_media_root与server_media_root。只映射已验证根下文件，URI做转义；服务端须以`--allowed-local-media-path`放行实际路径。两个根都应能覆盖原片及本轮派生媒体，或使用合适的共同挂载根。
- 原生video_url请求不会带Qwen的max_pixels等顶层私有字段。当前vLLM请求使用media_io_kwargs.video传fps、num_frames、覆盖完整输入时长的max_duration，避免继承默认截300秒或32帧。模型处理器仍可能有独立约束。
- 当前新版vLLM默认拒绝请求级多模态kwargs，可信客户端部署可使用`--trust-request-mm-kwargs`。不支持这些请求参数的旧部署，可设request_mm_kwargs=false，并在服务端预先配置同样的采样与完整时长；各角色FPS不同不能靠一个不匹配的全局默认糊弄过去。
- 模型专用resize/处理选项可放extra_body.mm_processor_kwargs；是否支持、是否需要信任开关由部署版本决定。客户端不自动重启vLLM、不下载权重、不调整GPU环境。
- sampling_verified是用户对该部署的能力声明，不是GET /models测出来的事实。未经真实预处理验证，provider_effective_sampling仍未知；不会在训练JSON中编造实际帧数。

依据：[vLLM多模态官方文档](https://docs.vllm.ai/en/latest/features/multimodal_inputs/)与[视频加载器官方源码](https://github.com/vllm-project/vllm/blob/main/vllm/multimodal/video.py)。本轮验证是localhost协议模拟，尚未连接用户的GPU服务；因此保证的是适配器路径及检查机制，不是任意vLLM模型/版本均已实测可用。

## 6. 配方与成本边界

完整运行先检查原片能否满足已配置的A7文件大小、帧数和base64传输边界，已知不可能送审则在caption费用发生前blocked。单独执行caption阶段不受A7的原片限制；用户可能只需先构造caption。file_uri传输也仍受所设max_video_bytes限制，不能通过换协议绕过资源边界。

新UI提供公开可修改的初始工程配方，不冒充先前已冻结的生产采样配置；旧runtime.example.json的null没有被悄悄填成已确认值。新建/run时都显示关键范围/角色/FPS，用户从私有配置持久修改。首轮10视频、30元、A1/A2/A7 2FPS是预置，不保证能处理任意时长/分辨率；质量与容量约束可能更早blocked。

逐角色使用该profile配置费率预约并按usage记账，不再拿一个Qwen费率给混合模型计价。预置Qwen北京0.8/2.7元每百万输入/输出；DeepSeek用高峰未缓存2/8元作为保守平价口径；并非核对后账单，优惠/缓存折扣不自动套用。自建vLLM的token API计价预置0，不代表GPU/电费免费，仍有请求数、视频数、上下文和输出上限。

价格依据：[Qwen官方价格](https://help.aliyun.com/en/model-studio/qwen3-8-flash)、[DeepSeek中文价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。用户可在模型profile覆盖rates。总预算不变：先预约再发送，usage缺失持有预约，超界中止，不增加重审、补题或自动重试。
