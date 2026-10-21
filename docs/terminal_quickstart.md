# 终端操作速查（v0.2）

## 启动

在服务器的仓库目录执行：

```bash
bash scripts/git/sync_pull_ff_only.sh
bash scripts/run_pipeline.sh
```

进入带状态面板、`❯`输入栏、斜杠命令和运行进度的终端界面。Python>=3.11；处理真实视频需FFmpeg/ffprobe。无需额外安装界面库。

## 第一次配置，之后复用

界面输入：

```text
/source /data/my_mp4
/output /data/video_sft_builds
/config edit
```

来源可为**MP4文件夹、单个MP4路径、HTTPS的MP4直链**；含空格的路径加引号。直链会下载到本轮`inputs/`，不支持把普通视频网页当MP4地址。原本地MP4不复制、不修改。

文件夹默认只处理当前层；要包含子目录，先`/set recipe.recursive true`。

私有配置自动建在 `~/.config/video-sft-builder/config.json`。`/config`可查看实际路径和脱敏内容；用`/config edit`或自己的编辑器修改。保留自动生成的其余字段，仅填写对应模型的`api_key`：

```json
"qwen3.8-flash": {
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "model": "qwen3.8-flash",
  "api_key": "在本机填入自己的Key"
}
```

也可输入`/key qwen3.8-flash`，隐藏输入并保存一次。每次构建都复用已存Key，不再粘贴；Key不会进入本轮产物或Git。环境变量Key仍可作为备用。

Qwen预置为北京endpoint及费率；更换地域或第三方代理时，要同步核对profile的`rates`。金额限制按配置费率计价。

## 每次构建

```text
/new my_batch
/run
```

只需提供本轮字符串`s`，例如`my_batch`或`动作数据`，目录自动命名为`my_batch_20261021_1651`，时间取服务器本地创建时间。名称允许字母、汉字、数字、下划线、短横线和点，不含空格或路径分隔符。同名同分钟已存在时拒绝覆盖，可恢复旧轮次或换名称。

`/run`前会展示冻结的来源、目录、API路由、FPS、视频数与预算。**界面初始配方是可修改的工程预置**：L1=10秒、L2=30秒，L1/L2/A7均2FPS；首批最多10视频、30元token计价预算。它们不是已实测的最佳质量参数，可先用`/set limits.max_videos 100`、`/set limits.max_cost_cny 50`等修改，之后新建轮次才生效。

也可分阶段执行：`/run prepare`仅预清理；`/run caption`到三级caption及门禁；`/run all`继续出题与审核。不会因分阶段重复已完成的模型请求。

## 模型选择

| 操作 | 命令 |
|---|---|
| 查看模型与Key是否配置 | `/models` |
| Qwen用于全部阶段 | `/model qwen3.8-flash`，并用`/route all active`清除旧覆盖 |
| DeepSeek出题/稀疏帧检查，Qwen看视频 | `/model deepseek-v4.1-flash`，再`/route video qwen3.8-flash` |
| 查看连接和served model是否存在 | `/models ping vllm`，只GET模型列表，不做推理 |

DeepSeek配置名叫`deepseek-v4.1-flash`，官方请求里的model实际为`deepseek-flash`。它不能单独跑本管道的原生视频阶段，必须明确路由A1/A2/A7到视频模型；程序不暗中换模型。

## 使用服务器上的vLLM

在`/config edit`里修改`models.vllm`：

- `base_url`：例如`http://127.0.0.1:8000/v1`，或实际内网地址。
- `model`：与vLLM的served model name一致；`provider_max_input_tokens`按实际部署容量填写。
- 按实际模型设置`capabilities`；视频阶段必须支持`video_url`，C_GATE要支持多图。
- 确认部署能保留配置FPS、全片范围和足够帧数后，将`sampling_verified`设为`true`；未确认时程序拦截。

然后输入`/model vllm`、`/route all active`。默认用base64传媒体，适合小视频。大视频推荐共享文件路径：在同一个vLLM配置里填写`local_media_root`、`server_media_root`，再把`transport`改为`file_uri`；服务端需放行该目录。`request_mm_kwargs=true`的当前vLLM需允许请求级多模态参数；具体部署要求见[接口与设计说明](terminal_ui_and_api_design_2026-10-21.md)。

大视频还要把该profile的`max_video_bytes`设为部署允许的大小（单位字节），不要只改传输方式。完整运行会提前检查A7所需的整片容量，不能送审就blocked，不先支付caption费用。

若自建的是纯文本模型，保持Qwen为默认，只用`/route text vllm`承担A3/A5即可。`/route`可查看所有新轮次的实际路由，避免旧覆盖仍然生效。

## 恢复、查看与退出

```text
/resume my_batch_20261021_1651
/status
/run
/quit
```

恢复沿用该轮的冻结配置；改默认模型、来源或预算只影响新轮次。API Key可以轮换，不写入冻结文件。运行中Ctrl+C保留中间数据；已发送但结果未知的请求不会自动重发。

本轮目录包含`runtime.json`、`build.json`、`state/`、`media/`、`artifacts/`、`reject/`、`exports/`、`reports/`和`terminal.events.jsonl`。`/report`显示报告路径，`review.md`可逐题审阅。输出仍是12字段自动审核候选，CoT另建链路。

不接API也能先体验：`/demo try_ui`。它全程模拟，不处理真实视频、不产生实际费用。

自定义私有配置位置：`bash scripts/run_pipeline.sh ui --settings /absolute/private/config.json`；纯文本终端可追加`--plain`。配置建议置于本地持久磁盘；本轮`state/`使用SQLite和文件锁，输出目录所在文件系统须可靠支持这些能力。
