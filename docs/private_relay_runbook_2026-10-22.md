# 指定轮次与原视频的私有中转（2026-10-22）

## 当前状态与范围

用户明确要求创建私有中转仓库，将本次构建产物及原视频传回检查，并保证服务器仅从Public代码仓库下载。已创建并通过GitHub查询确认私有：[Tiachi/video-sft-builder-relay](https://github.com/Tiachi/video-sft-builder-relay)。Public代码仓库仍为`Tiachi/video-sft-builder`。

本次授权仅覆盖用户指定的一轮构建目录和一个原始MP4，不扩大为上传整个数据根目录、其他轮次、模型权重、模型API配置或账户凭据。数据使用**私有仓库的Release附件**中转，不进入Public仓库，也不放入任何仓库的Git文件历史。

`pending`表示仍有未完成实体，不能当作构建完成。以60秒原片、10秒/30秒配方为例，完整caption阶段应有6个L1、2个L2，L3复用末次L2；若只看到少量切片或caption，应先核查实际账本、事件和原片metadata，不据文件数量直接认定根因，不直接重跑或增加预算。真实路径、产物与诊断证据留在私有中转，公共手册仅记录通用操作。

## 一次性准备私有仓库认证

Public仓库HTTPS下载无需凭据；私有中转上传必须认证。这两个权限独立。推荐在[GitHub创建Fine-grained Token](https://github.com/settings/personal-access-tokens/new)：

- Resource owner：`Tiachi`。
- Repository access：**Only select repositories**，只选择`video-sft-builder-relay`。
- Repository permissions：**Contents → Read and write**；Metadata保留必要的Read。
- 设置较短有效期；不要给Public代码仓库写权限，不要在聊天中发送Token。

第一次运行上传命令时，在服务器隐藏输入该Token；验证能访问正确私有仓库后才保存一次，位置为`~/.config/video-sft-builder-relay/token`，目录700、文件600。与模型API Key分开，不会写进产物包、代码、日志、数据库或Git。若服务器已有可用`gh`登录，也可复用现有身份；环境变量`VIDEO_SFT_RELAY_TOKEN`可作为其他受控凭据注入方式。

只读Token不能上传。遇到HTTP404通常是Token未覆盖这个私有仓库或资源确实不存在；HTTP403需核对Contents写权限、有效期和账户策略。工具不打印Token或GitHub原始错误响应体。

## 服务器操作

先退出管道终端，确保当前没有`/run`执行；在服务器的Public代码仓库根目录拉取工具：

```bash
bash scripts/git/sync_pull_ff_only.sh
```

传入本次待检查的来源与产物绝对路径，执行这一条上传命令（路径需替换）：

```bash
bash scripts/relay_current_run.sh --build /absolute/path/to/selected_build --video /absolute/path/to/original.mp4
```

命令结束应打印`PASS: private relay upload complete:`及Release URL；把该URL发回检查即可。若网络中断，使用命令已打印的`--resume`路径恢复**诊断包上传**，不会重跑数据管道或重发模型请求。

```bash
bash scripts/relay_current_run.sh --resume /absolute/path/to/_private_relay/evidence-...
```

只想先在服务器生成包、不联网、不修改Git推送设置，可在首次命令后加`--pack-only`。这时不请求GitHub凭据，也不上传。

## 上传与保护行为

| 环节 | 行为与I/O |
|---|---|
| 依赖 | 只检查已有Python/标准库，不安装包、不调用模型、不要求重新安装FFmpeg |
| Public仓库保护 | 核对仓库根和origin身份；仅在本服务器checkout的`.git/config`中将`remote.origin.pushurl`设为`disabled-public-push://video-sft-builder`，保留fetch URL；普通`git push origin`因此失败，快进拉取照常 |
| 上传目的地 | 所有GitHub API路径固定在`Tiachi/video-sft-builder-relay`，每个附件发送前确认`private=true`；仓库不匹配/已变Public则拒绝 |
| 快照锁 | 使用该轮`coordinator.lock`，运行中拒绝打包；不读取同级其他轮次 |
| 产物 | 指定轮次中的已知顶层JSON/事件、artifacts、reports、exports、reject、media、inputs及SQLite诊断副本；未知文件、凭据文件、符号链接和不支持扩展名记录排除 |
| 原片 | 只读取明确传入的MP4，按字节复制为`original/source.mp4`；前后校验源文件stat和SHA256，不转码、不覆盖源文件 |
| SQLite | 从只读连接备份；只在副本清空上传链接缓存、脱敏文本，再secure_delete/VACUUM；不对原账本做UPDATE，不加载生产Store或触发恢复逻辑 |
| 脱敏 | 排除外部私有配置；移除常见凭据字段、Token形状、URL账号/查询串；发现私钥拒绝。诊断JSON/SQLite可能因脱敏改变字节，manifest分别记录源和副本checksum |
| 限额 | 仅扫描指定轮次，最多10000个条目、输入总量2GiB、单个文本32MiB；原片精确路径顺序读取；不遍历`/mnt/sfs`其他目录 |
| 临时空间 | 写在构建父目录的`_private_relay/evidence-...`下，原轮次外、代码checkout外；原片/快照/压缩包/分片同时存在，需预留额外空间。失败保留包供恢复，不自动删除用户产物 |
| 完整性 | 32MiB分片；源文件、快照文件、整体压缩包、分片均有SHA256；上传后核对GitHub附件的size与digest；manifest最后上传作为完成标识 |
| Git | 上传是私有Release资产API；脚本从不执行git add/commit/push，不更改Public仓库文件或源代码指纹 |

Public的只下载保护是服务器本地默认Git推送配置加上推荐的仓库专用Token权限，不应被手工覆盖；不会给账户颁发或扩大Public写权限。开发机器仍可按既有流程发布代码。

## 检查顺序

接收方先确认私有仓库和`manifest.json`完成标识，再下载诊断摘要、分片并核对hash。检查内容：原片实际时长/帧率、caption窗口规划与完成记录、两个切片对应的窗口、请求状态和finish_reason、usage/预算预约、pending事件及其原因，之后再决定是否需要查看完整视频/具体caption。

`diagnosis.json`会自动汇总上述可直接读取的状态；能用服务器ffprobe时，额外探测仅这一份原片。它不推断真实根因，不以pending数量代表失败视频数，不改变已有生产状态。后续检查结论应分别记录直接证据、推断与未验证项。

该包是**只供诊断的脱敏副本**，不能拿回服务器替换runtime、SQLite或产物。严禁把诊断包、原片、Release下载签名URL、令牌或真实模型响应再提交到Public代码仓库。

接口依据：[GitHub Release API](https://docs.github.com/en/rest/releases/releases)、[附件上传/读取与摘要字段](https://docs.github.com/en/rest/releases/assets)。私有仓库创建、本地11项专项验证及真实私有API上传/下载校验已完成；网络闭环只用175字节的模拟输入，并非真实视频，4个快照文件及整体归档的hash均核对通过。真实服务器产物尚未上传、尚未检查。

本次完整回归113项，111通过、2项因开发机没有真实FFmpeg而跳过，耗时91.512秒；设计合同、上传包装脚本Bash语法和CLI帮助检查通过。公共仓库只发布工具/测试/文档；模拟包、下载缓存、接收回执和测试日志均未进入Git。未修改生产Python模块、prompt或配方，原轮次的代码/资产指纹不变。
