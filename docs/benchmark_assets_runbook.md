# Benchmark 下载与统计速查

范围：9 个视频 benchmark（MLVU dev/test 分两个下载单元），不运行 SFT／标注／评测，不调用模型 API。分类与题数见[研究表](video_benchmark_inventory_and_tasks_2026-10-22.md)。

服务器已有 checkout：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
bash scripts/git/sync_pull_ff_only.sh && bash scripts/benchmarks/run.sh download
```

下载使用直连，默认不用个人代理。首次会自动创建独立工具环境、从清华 PyPI 安装依赖；父终端网络配置不改。读取现有 HF 登录，不要求粘贴 Key；Token 只发送官方 HF。官方 gated 仓库不通／缺授权时会 blocked，继续其他项目，整体非零结束。

同一命令可以重跑续传。已有原文件不写入；按固定 revision 存到新目录。已有视频引用全覆盖时复用，部分资产按精确路径和大小复用，不把旧 val 子集冒充全量。

本轮新产物统一放在：

```text
/mnt/sfs/ltj/data/benchmark_research_20261022/
  snapshots/                 官方视频、标注、归档，按数据集/revision 分开
  reports/<UTC时间>/report.json
  latest_report.json         最新报告路径及 status
  _tools/venv/               工具依赖
```

查看最新报告位置：

```bash
cat /mnt/sfs/ltj/data/benchmark_research_20261022/latest_report.json
```

脚本也会在开头和结束打印本轮 `report.json` 路径。报告区分 `download_status`、分类统计、缺 NTU/YouTube 等 blocker、媒体是否解包／解码。**当前归档只下载、不自动解包，媒体内容尚未验证；不能将包下载完成叫做评测准备完成。** MMVU 隐藏 test 不公开下载；MotionBenchCaption-train 不属于本轮 benchmark 范围。

只检查已登记资产与已下载标注，不下载 benchmark：

```bash
bash scripts/benchmarks/run.sh inventory
```

首次 inventory 仍可能安装工具包。既有路径和来源配置见 [benchmark_assets.json](../configs/benchmark_assets.json)；若数据存放在其他路径，只修改该配置的 `media_roots`／`existing_annotations`，不要移动原数据。数据／缓存／完整报告都不能加入代码 Git。

验证边界：新增 9 项离线边界测试通过；全项目 174 项测试通过（2 项 FFmpeg 媒体测试因环境条件跳过），Bash 语法检查通过。真实服务器 SSH、下载、授权及媒体完整性待服务器报告确认。
