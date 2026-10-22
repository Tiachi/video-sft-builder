# 终端操作速查（v0.2）

## 首次从GitHub下载到Linux服务器

本仓库已改为 **Public**。使用下面的HTTPS地址克隆和拉取更新，**无需登录GitHub、SSH密钥或GitHub访问令牌**。模型推理仍需要你自己的API Key，填写方法见后文。

在Linux服务器上执行，以下用`~/projects`作为代码父目录，可改为自己希望的位置：

```bash
mkdir -p ~/projects
cd ~/projects
git clone --branch main --single-branch https://github.com/Tiachi/video-sft-builder.git
cd video-sft-builder
bash scripts/run_pipeline.sh
```

`clone`在父目录执行；运行脚本在克隆出的`video-sft-builder`仓库根目录执行。刚克隆时已取得最新代码，无需再执行同步脚本。同名非空目录已存在时不要删除，进入原有仓库按下一节更新。

如果此前使用SSH地址克隆，而现在希望不配置密钥即可拉取，在原有仓库根目录执行一次：

```bash
git remote set-url origin https://github.com/Tiachi/video-sft-builder.git
```

仍使用SSH地址时，SSH认证要求不变；仓库变为Public不会让SSH协议自动匿名。推送代码仍需有写入权限并完成认证。公开范围包含代码、文档及其Git历史；真实视频、产出数据和私有模型配置继续放在仓库外。

## 后续更新与启动

例如首次克隆在`~/projects`下，之后每次在服务器执行：

```bash
cd ~/projects/video-sft-builder
bash scripts/git/sync_pull_ff_only.sh
bash scripts/run_pipeline.sh
```

如果选择了其他克隆位置，将`cd`路径换成实际位置。同步脚本要求当前为干净的`main`分支，只允许快进更新；提示本地修改时先保留并处理自己的修改，不会自动覆盖。

服务器访问GitHub超时、仅本机有Clash时，可通过“UU映射服务器SSH→SSH反向转发本机代理”恢复Git访问。完整映射方向、启动命令和只影响本仓库的代理设置/还原见[服务器网络配置](server_git_proxy_via_uu_2026-10-22.md)；不能直接把本机127.0.0.1代理地址当成服务器上已存在的服务。

启动脚本会先检查 **Python>=3.11、SQLite/SSL、FFmpeg和ffprobe**，缺失时自动尝试安装，然后用程序生成的0.5秒小视频验证H.264编码、视频探测及灰度/JPEG抽帧，全部通过才进入界面。初始化不读取你的MP4、不调用模型、不消耗API额度。

Linux优先使用已激活的Conda环境（需有`CONDA_EXE`）；否则使用当前系统的apt/dnf/yum/zypper/pacman源。已有依赖不会重复安装；系统安装需要root或免密sudo。系统源缺包、无权限、网络错误或FFmpeg缺编码器时，明确FAIL并停止；不会自动添加第三方系统源。项目Python运行库都是标准库，无需安装torch、transformers或额外界面库。

兼容Ubuntu 22.04系统源的FFmpeg 4.4：程序检测实际选项，旧版自动使用`-vsync 0`，新版优先使用`-fps_mode passthrough`。两者都选择时间戳透传；初始化会打印所选模式，正式裁片使用同一规则。此前已装好FFmpeg但报`Unrecognized option 'fps_mode'`时，更新代码即可，无需为此重新安装FFmpeg或创建Conda环境。

只检查、不允许安装：`bash scripts/bootstrap.sh --check`。只初始化、不启动界面：`bash scripts/bootstrap.sh`。如系统软件源没有完整FFmpeg，可在已有Conda中创建环境后继续：

```bash
conda create -n video-sft-builder -c conda-forge python=3.11 ffmpeg -y
conda activate video-sft-builder
bash scripts/run_pipeline.sh
```

指定现成Python可用`VIDEO_SFT_PYTHON=/absolute/path/to/python bash scripts/run_pipeline.sh`；禁用自动安装可用`VIDEO_SFT_AUTO_INSTALL=0 bash scripts/run_pipeline.sh`。完整初始化行为和验证边界见[依赖初始化说明](dependency_initialization_2026-10-22.md)。

初始化通过后，进入带状态面板、`❯`输入栏、斜杠命令和运行进度的终端界面。已有私有配置与构建目录不会因依赖安装被重建。

## 第一次配置，之后复用

界面输入：

```text
/source /data/my_mp4
/output /data/video_sft_builds
/config edit
```

来源可为**MP4文件夹、单个MP4路径、HTTPS的MP4直链**；含空格的路径加引号。直链会下载到本轮`inputs/`，不支持把普通视频网页当MP4地址。原本地MP4不复制、不修改。

文件夹默认只处理当前层；要包含子目录，先`/set recipe.recursive true`。

发现的视频数超过`limits.max_videos`会明确报错，不静默处理前N个；请明确选择单个MP4/allowlist，或调整限额后新建轮次。

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

出现“未完成”时查看停止角色/窗口及L1、L2完成/计划数量；`status.json`和报告也标incomplete，部分导出manifest不会标完整。终端退出返回非零状态。不要因为有导出目录就认为整轮已经完成。强制结束后若显示running，也不能当完成。

**升级代码后恢复早期caption错误**：代码指纹变化时不要删除SQLite或直接重跑旧轮次。在终端输入`/recover /absolute/old_build fixed`，再`/run all`。新建的`fixed_YYYYMMDD_HHMM`仅在精确匹配时复用旧已付费A1/A2响应，保留旧轮次、原文和历史费用；未知执行请求拒绝恢复，不自动重新收费。此入口目前仅支持所有请求已知完成的caption阶段旧轮次。详情见[完整性与恢复说明](no_silent_truncation_2026-10-22.md)。

不接API也能先体验：`/demo try_ui`。它全程模拟，不处理真实视频、不产生实际费用。

自定义私有配置位置：`bash scripts/run_pipeline.sh ui --settings /absolute/private/config.json`；纯文本终端可追加`--plain`。配置建议置于本地持久磁盘；本轮`state/`使用SQLite和文件锁，输出目录所在文件系统须可靠支持这些能力。

## 把异常轮次私有传回检查

独立私有中转仓库为`Tiachi/video-sft-builder-relay`。上传一轮产物和一个原MP4用`bash scripts/relay_current_run.sh --build /absolute/build --video /absolute/original.mp4`；首次在服务器隐藏输入仅授权该私有仓库的GitHub Token。工具禁用该服务器代码副本向Public origin推送，产物只进入私有Release附件。详细步骤、当前轮次命令与恢复方式见[私有中转手册](private_relay_runbook_2026-10-22.md)。
