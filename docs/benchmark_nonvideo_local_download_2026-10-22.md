# 五项 Benchmark 非视频文件：本机下载记录

完成日期：2026-10-22。用户要求：Video-MME、Video-MME v2、LVBench、Video-MMMU、MMVU 的非视频部分下载到本机；若五项总量超过 1 GB，停止且不下载正文。

## 已完成

本机目录：`C:\Users\Tiachi\Documents\Dataset\x_temp\benchmark_nonvideo_20261022`。

**34 个文件，112,343,054 字节（112.34 MB；约 107.14 MiB）；官方文件清单逐项核验完成，缺失 0，视频 0。** 这里是数据载荷大小，不包含小型计划／校验报告和下载工具代码。总量远小于 1,000,000,000 字节上限。

| 目录 | 已验证文件数 | 字节数 | MB（十进制） | 包含内容 |
|---|---:|---:|---:|---|
| `Video-MME` | 4 | 7,912,613 | 7.91 | QA Parquet、字幕 zip、README、Git 属性文件 |
| `Video-MME-v2` | 8 | 13,518,736 | 13.52 | QA Parquet、字幕 zip、说明图片、eval.yaml、README、Git 属性文件 |
| `LVBench` | 12 | 4,906,020 | 4.91 | QA JSONL、说明图片、许可证、README、Git 配置文件 |
| `Video-MMMU` | 5 | 78,298,079 | 78.30 | 三认知轨道 Parquet、README、Git 属性文件；Adaptation 内含查询图片 |
| `MMVU` | 5 | 7,707,606 | 7.71 | 公开 validation JSON、说明图片、README、Git 属性文件 |
| 合计 | **34** | **112,343,054** | **112.34** | 不含视频或视频归档 |

“全部”指该日期固定 revision 下的官方 HF 仓库中所有非视频文件；不包含未公开的 MMVU hidden test。字幕 zip 原样保存，未自动解压。LVBench 的 YouTube 视频、Video-MMMU 学科视频归档与 question-only 视频归档、Video-MME 系列视频包和演示 MP4 全部排除。

## 校验与来源

- 先取得五项完整文件清单及字节数，执行总量门禁，确认 112.34 MB 后才开始下载数据文件。元数据查询不算数据正文下载。
- LFS 文件按官方 SHA256 验证；普通 Git 文件按 `SHA1("blob <size>\0" + bytes)` 与官方 blob ID 验证；每个文件同时核对大小。已有研究缓存只在内容哈希一致时复用。
- 四项公开仓库经匿名 HF mirror 获取；Video-MMMU 的三个受限 Parquet 和 README 由用户使用已授权 HF 浏览器下载，再由脚本验证并复制归档。原 Downloads 文件保留，没有读取或导出浏览器 Cookie／HF Token。
- Video-MMMU 的 `.gitattributes` 与已下载 MMVU 文件的官方 Git blob ID 完全相同，因此复用同内容文件并再次校验，未臆造仓库文件。
- 字幕 zip 完成 CRC 校验，且归档条目无视频扩展名。原始标注、图片、压缩包没有改写或转码。

| 数据集 | 官方仓库 | 固定 revision |
|---|---|---|
| Video-MME | [lmms-eval/Video-MME](https://huggingface.co/datasets/lmms-eval/Video-MME) | `ead1408f75b618502df9a1d8e0950166bf0a2a0b` |
| Video-MME v2 | [MME-Benchmarks/Video-MME-v2](https://huggingface.co/datasets/MME-Benchmarks/Video-MME-v2) | `6e4bebb03202e1ddbf3d37703e560e51c5aa2d64` |
| LVBench | [zai-org/LVBench](https://huggingface.co/datasets/zai-org/LVBench) | `0caedb92002cc268bad486449e551c76f0485670` |
| Video-MMMU | [lmms-eval/VideoMMMU](https://huggingface.co/datasets/lmms-eval/VideoMMMU) | `d1c35ac933123d79e877b7f1b9506afb0309cf1b` |
| MMVU | [yale-nlp/MMVU](https://huggingface.co/datasets/yale-nlp/MMVU) | `b937f414a87e9012acba49d95669020b24fa9ee9` |

本机数据目录中的 `download_plan.json` 包含每个文件的来源、revision、size、Git/LFS 哈希和被排除视频文件清单；`download_report.json` 是独立重算的最终完成状态；`_metadata/` 保留来源元数据。上述文件和原始数据均不提交 GitHub。

## 工具及验证边界

工具：[nonvideo_local.py](../scripts/benchmarks/nonvideo_local.py)。使用标准库＋curl，不依赖训练环境，不调用模型、不连接服务器。支持 `plan`、`download`、`adopt`、`adopt-downloads`、`verify`；在下载和导入前重新检查整批 1 GB 上限，遇到未知文件大小／未分类归档／已有文件冲突会停止。

新增 5 项离线测试通过，覆盖整批门限、未知大小拒绝、视频归档排除、路径安全、内容哈希和已有文件保护。实际本机下载／人工浏览器导入及最终内容哈希核验已执行；不是仅有离线测试。没有运行模型评测，也不把数据质量判断等同于文件完整性校验。

本次仅在本机写入数据；不改变服务器正在运行的任务。GitHub 仅备份工具、测试和本记录，任何 benchmark 载荷都不上传。
