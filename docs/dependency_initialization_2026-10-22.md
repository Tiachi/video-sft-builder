# 启动依赖初始化与故障恢复（2026-10-22）

## 问题与变更

用户提供的服务器终端记录表明：仓库已克隆，终端启动、配置保存与轮次创建成功，但`/run`在`FFmpegMedia.doctor()`处报`Media tool missing, failed to start or timed out`。这说明本地媒体工具检查未通过，尚未执行模型调用；仅凭该通用错误不能断言具体是缺少ffmpeg、ffprobe、共享库还是超时。

此前启动脚本直接执行Python模块，遗漏了依赖初始化。初次修复`cfe1fb5`使`bash scripts/run_pipeline.sh`默认先调用`bootstrap.sh`，环境检查通过后才加载终端；该次没有修改`src/`。随后根据用户服务器反馈补充下节FFmpeg版本兼容修复，本次涉及`src/`的媒体参数选择，代码指纹会变化。

## FFmpeg 4.4兼容修复

用户随后提供的服务器日志确认：Ubuntu Jammy arm64的软件源成功安装FFmpeg/ffprobe 4.4.2和libx264，安装本身成功；初始化失败的明确原因是`Unrecognized option 'fps_mode'`。这是项目选项兼容遗漏，不应要求用户为此换源或重装环境。

新增`src/video_sft_builder/ffmpeg_compat.py`，读取实际可执行文件的`-hide_banner -h full`帮助输出，根据选项声明选择：

| 运行时能力 | 生成选项 | 行为 |
|---|---|---|
| 声明`-fps_mode` | `-fps_mode passthrough` | 优先使用现代逐流透传模式 |
| 未声明`-fps_mode`，声明`-vsync` | `-vsync 0` | 使用旧版透传模式，支持4.4 |
| 均未声明/帮助检查失败 | 停止并报告 | 不静默转为CFR、auto或重新编码其他配方 |

初始化自检和`FFmpegMedia.clip()`共用选择函数；正式媒体对象缓存能力查询。保留原有裁片起止、时长、编码参数、时间映射、校验与原片只读规则。不增加模型调用，不在失败后付费重试。初始化输出会明确打印`PASS: FFmpeg timing mode: -vsync 0`或现代选项。

依据：[FFmpeg 4.4.2官方源码文档](https://github.com/FFmpeg/FFmpeg/blob/n4.4.2/doc/ffmpeg.texi)将`-vsync 0`定义为passthrough；[当前官方文档](https://ffmpeg.org/ffmpeg.html#Advanced-options)定义`-fps_mode passthrough`。二者语义均保留帧与时间戳，封装层仍可能影响最终时间戳，因此项目既有裁片时长与源时间映射检查继续执行。

本次会改变代码指纹。用户目前贴出的失败发生在启动自检或之前的`doctor()`阶段，尚未创建请求账本，可以恢复原先只含build/runtime的轮次。对其他已在旧代码下创建SQLite账本或发送请求的轮次，继续保持指纹保护，不自动迁移、删库或重发；应使用原提交恢复或另行审查迁移。

## 文件与执行顺序

| 文件 | 工作 | 输入/输出与调用范围 |
|---|---|---|
| `scripts/run_pipeline.sh` | 启动前执行初始化，使用已选定的Python启动终端 | 命令参数；不新增模型调用 |
| `scripts/bootstrap.sh` | 选择Python、检查标准库，发现缺失/无法运行的媒体工具时安装，再运行自检 | PATH、可选环境变量、已配置软件源；依赖安装输出写终端，不读取私有配置 |
| `scripts/check_environment.py` | 检查Python>=3.11、SQLite/SSL，验证两项可执行程序，生成0.5秒64×64测试视频并验证libx264编码、ffprobe、灰度/JPEG抽帧 | 仅操作系统临时目录，退出后删除自己生成的测试目录；不读取用户MP4 |
| `tests/test_bootstrap.py` | 隔离PATH并用假包管理器注入成功、缺包、权限、安装失败等情况 | 临时小文件，绝不调用实际系统安装器 |

Python运行依赖为标准库，无需`pip install`、torch、transformers或视频模型权重。检查包括实际管道选择的透传选项与默认libx264编码能力；只有`ffmpeg -version`成功不够。

## 安装规则与边界

1. 优先复用现有Python>=3.11；`VIDEO_SFT_PYTHON`可明确指定解释器。指定路径错误直接失败，不擅自换解释器。
2. 已激活Conda且存在可执行`CONDA_EXE`时，在该前缀安装缺失依赖，使用conda-forge；否则依次识别apt-get、dnf、yum、zypper或pacman。
3. 系统安装只新增所需包：Python缺失时尝试python3.11（Arch为python），媒体工具缺失/无法启动时安装完整ffmpeg与ca-certificates。不执行系统整体升级，不自动更换系统Python链接，不添加第三方系统源或使用`--allowerasing`。
4. root直接安装；非root仅使用已有免密sudo，避免应用启动期间挂住等待口令。无权限则清楚失败，管理员可先运行初始化脚本。
5. 已有工具通过检查时不运行包管理器。若可执行文件能启动但缺编码器/参数，自检报错并停止，不反复重装或静默改变裁片编码。
6. dnf/yum基础源不一定提供完整ffmpeg；精简的ffmpeg-free也不保证libx264可用。源不可用或平台不支持时不承诺自动装成：保留错误，使用管理员准备的环境或已有Conda；示例见[操作手册](terminal_quickstart.md)。FFmpeg官方也将Linux预编译包分发交给各发行版/打包方，见[下载说明](https://ffmpeg.org/download.html)。
7. 所有工具子进程检查有15/20秒超时；包管理器可能需要较长下载/求解，输出直接显示在终端。系统源可用性、锁、网络及权限仍属运行环境条件。

`--check`或`VIDEO_SFT_AUTO_INSTALL=0`禁止安装。`demo`、`--help`、`init-config`、`validate-config`、`report`和`export`等入口不要求媒体工具，保留离线/只读用法。直接执行Python模块或安装后的console entrypoint不经过Bash初始化；推荐始终使用仓库启动脚本。

## 现有轮次恢复

先退出旧终端，然后在现有仓库根目录执行：

```bash
bash scripts/git/sync_pull_ff_only.sh
bash scripts/run_pipeline.sh
```

依赖检查通过后，在界面中恢复原轮次，继续执行即可，无需重填API Key、来源或输出目录。例如用户日志中的轮次：

```text
/resume video1_test_20261022_0906
/run
```

源视频、私有配置、已有runtime/build文件、SQLite和派生产物都不被初始化脚本读取或覆盖。此次用户报错位于Store创建之前；正式恢复仍按既有冻结配置、请求账本和不自动重发规则执行。

## 验证状态

当前FFmpeg 4.4兼容修复：全套102项测试在71.062秒内结束，100通过、2跳过、0失败。新增7项覆盖旧版选项、现代选项优先、无legacy选项的新版、无法识别能力时拒绝、能力查询缓存、自检两个选项路径、真实裁片方法的命令/发布/时间侧车与原文件保留；底层FFmpeg命令使用替身。两项跳过仍是当前开发机缺少真实FFmpeg；未宣称已在用户arm64服务器上复测通过。Bash语法、真实Python的无媒体检查、设计合同与diff检查通过。

初次依赖初始化修复的历史验证：全套95项测试在89.627秒内结束，93通过、2跳过、0失败；新增16项中15通过、1跳过，覆盖系统源安装、Conda、Python安装顺序、重复运行不重装、权限不足、安装失败拦截、编码能力失败拦截与父shell存活。包管理器均为隔离替身。

设计检查`validate_design.py`通过；两份Bash脚本语法检查通过；使用真实Python的`run_pipeline.sh --help`与`bootstrap.sh --check --no-media`通过，且显式禁止安装。未连接用户Linux服务器，未实际执行apt/dnf/Conda安装，也未调用真实模型；不能用替身测试宣称任意Linux发行版均已实测安装成功。
