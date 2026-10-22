# Linux服务器同步入口

仓库：`Tiachi/video-sft-builder`，公开（Public），稳定分支main。代码目录的最终父路径由用户选择，以下首次命令在该父目录执行。

```bash
git clone --branch main --single-branch https://github.com/Tiachi/video-sft-builder.git
```

该命令新建`video-sft-builder`目录，已有同名非空目录时Git会拒绝，不应删除现有目录以强行继续。使用上述HTTPS地址克隆或拉取不需要登录、SSH密钥或token；推送代码仍需要写入权限和认证。

进入`video-sft-builder`后，检查/同步运行：

```bash
bash scripts/git/sync_pull_ff_only.sh
```

脚本核验自己的Git根、origin身份、main分支、干净状态与快进关系。它拒绝dirty、本地领先/分叉、错误origin，不stash/reset/clean，不安装依赖或执行数据处理。同步成功打印完整提交SHA；应与发布方提供的SHA相同。远端在核验期间变化会失败并保留现场，稍后在干净状态重新同步。

脚本只读Git状态，网络读取origin，并在快进时更新此代码checkout；不访问MP4根目录、派生目录、API密钥或模型服务。Git在此checkout中仍有ignored的本地文件时需自行保留，媒体和派生产物应放checkout外。

数据管道入口现为`bash scripts/run_pipeline.sh`，首次下载、终端配置与启动见[简洁操作手册](terminal_quickstart.md)；旧JSON入口见[runtime_runbook.md](runtime_runbook.md)。同步只代表代码/文档已到服务器，不代表API/视频处理已运行。服务器路径和HEAD未经回传核查前，不声明服务器同步完成。
