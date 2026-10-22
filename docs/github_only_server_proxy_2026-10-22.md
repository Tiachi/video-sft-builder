# 服务器独立 GitHub 专用代理

**当前暂停部署。** 用户随后提供了直连 SSH 443 的 Git 检测成功结果，并要求简化。优先按[直连 SSH 443](github_direct_ssh443_2026-10-22.md)处理当前代码拉取；不要继续上传/安装本页私有代理包。本页保留此前实现与验证记录，不代表仍要求用户部署。

日期：2026-10-22。用户本次明确授权：使用其已有 Clash 配置，在服务器配置仅限 GitHub 使用的个人代理。该授权限定本方案的 GitHub 域名和操作，不扩展到 HF、模型、依赖、模型 API 或其他站点。

## 方案与范围

服务器运行独立 Mihomo 内核，通过用户配置中的一个 AnyTLS 节点连接 GitHub。不需要本机 Clash 持续在线，也不依赖 SSH 反向转发。SSH 和 UU 故障与服务器到 GitHub 的出网是两段链路：本方案改善后者，不能宣称能修复 UU 的 SSH 握手。

采用两层限制：

1. 仅本项目仓库的本地 Git 配置 `http.https://github.com/.proxy` 指向 `http://127.0.0.1:17898`，同一 URL 设置 HTTP/1.1。不写全局 `http.proxy`，不设置 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`。服务器 Public origin 的禁推送配置保留。
2. 代理内核只有 `github.com`、`githubusercontent.com`、`githubassets.com` 三个域名后缀规则通向唯一节点，最后 `MATCH,REJECT`。后两者覆盖 GitHub 的 raw/Release 附件等服务；`github.com.evil.example` 不匹配。即使其他程序误指向这个入口，非 GitHub 目标也不能通过该入口访问。

HF、pip、apt、模型 API 沿原有网络配置访问；本方案不给它们加代理，也不修复其直连网络。GitHub Release 并非自动全部代理：只有明确使用此入口的下载命令才走它；本项目 Git HTTPS 同步会自动按上述本地配置使用它。不对任意站点提供代理服务，不开放局域网代理端口，不修改系统路由或开启 TUN。

只保留单节点，没有自动测速、自动切换、订阅更新、远程规则集、Geo 数据更新或外部控制面板。失败时停止或报错，不换节点、不降低限制。普通 Git 请求和代理握手仍会消耗少量流量；GitHub 大附件仍可能很大，不承诺“GitHub 流量天然很小”。

依据：[Git URL 对应配置及匹配规则](https://git-scm.com/docs/git-config#Documentation/git-config.txt-httplturlgt)、[Mihomo 域名后缀与末尾匹配规则](https://wiki.metacubex.one/config/rules/)、[Mihomo 全局配置和 Geo 自动更新](https://wiki.metacubex.one/config/general/)、[官方 ARM64 Release v1.19.33](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.33)。

## 已准备与验证边界

| 项目 | 状态 |
|---|---|
| 服务器架构 | 用户实际执行 `uname -m`，确认 `aarch64` |
| 用户配置结构 | 本机私下读取，69 个内联 AnyTLS 节点；导出其中一个，原文件不改；不在文档/终端公开节点地址、密码、订阅 |
| 内核 | 官方 `mihomo-linux-arm64-v1.19.33.gz`，20,824,326 字节；官方 GitHub API 资产摘要 `ba408b317080ee265c46cb923a50018c1b82cbd708551cdd46a1e3e307396187` 已与下载字节核对 |
| 配置 | 已生成单节点、GitHub 白名单私有 JSON（Mihomo 支持的 YAML 子集） |
| 本机检查 | 11 项隔离测试通过：7 项策略/Git 测试覆盖白名单、拒绝策略篡改、重复键、实际临时 Git URL 隔离、失败不改配置、回滚、保留禁推送、拒绝已有广域代理；4 项私有打包测试覆盖摘要、精确载荷和不覆盖/不进入代码仓库；Bash 语法通过，本机已安装 Mihomo `-t` 接受配置 |
| 服务器 | SSH 握手超时，尚未安装、启动或实测 GitHub 出网；选中节点在服务器的可达性/账户余量也未验证 |
| 私有包 | 仅存本机代码仓库外，包含节点凭据，禁止上传任何 GitHub 仓库/Release或作为公开附件 |

本机 Windows 内核语法通过不能替代 Linux ARM64 运行验证。部署脚本在服务器先用提供的 ARM64 内核检查配置，再启动；只有 GitHub `ls-remote` 在 25 秒内成功，才写 Git 配置。该验证只取公开 main 引用，不下载仓库或速度测试文件。

## 文件与代码

公开代码只有：

- `scripts/git/github_only_proxy.py`：本机安全导出、Linux 安装/启动/状态/停止、GitHub URL 配置及恢复；Linux 部分只需 Python 标准库，YAML 导出在本机需要 PyYAML。
- `scripts/git/setup_github_only_proxy.sh`：组合安装、启动、GitHub 小请求检查及本地 Git 配置；不下载或安装依赖，失败明确 FAIL。
- `scripts/git/package_github_proxy.py`：离线验证官方 gzip 摘要并生成新的私有 ZIP，禁止输出至代码仓库，要求代码已提交且干净。
- `tests/test_github_only_proxy.py`：不访问真实节点的隔离测试。

私有 ZIP 的 `github-only-proxy-arm64/` 中有内核、单节点 `config.json`、内核 SHA256、上述部署脚本和代码/内核来源清单。ZIP 不加密，必须当作凭据保管；不能上传 GitHub，即使仓库私有。只经用户选择的可信传输路径送入自己的服务器。

安装落点：`~/.local/share/video-sft-github-proxy/`，目录 0700，配置 0600，代理日志只保存在该私有目录。Git 原值备份只在目标仓库 `.git/github-only-proxy-backup.json`，不会提交。脚本不接触原视频、构建数据库或 QA 产物，不停止管道进程。

## SSH 不通时的手动部署

先将本机准备好的 `github-only-proxy-arm64.zip` 通过你认可的私有传输方式放到实验室电脑。当前助手没有成功 SSH，不能替你完成这一步或声称服务器已经有此文件。假设放到实验室电脑 Windows 的 Downloads 目录，在该电脑 PowerShell 执行：

```powershell
scp "$env:USERPROFILE\Downloads\github-only-proxy-arm64.zip" audio_1:/root/
```

然后在已经登录的服务器终端执行。目标目录不存在时才解包，避免覆盖之前传来的安装包：

```bash
test ! -e /root/github-only-proxy-arm64 && python3 -m zipfile -e /root/github-only-proxy-arm64.zip /root
bash /root/github-only-proxy-arm64/setup_github_only_proxy.sh /root/github-only-proxy-arm64 /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
```

不需要 pip、apt、外网订阅拉取或先从 GitHub 下载内核，避免“要先连上 GitHub 才能装 GitHub 代理”的循环依赖。该包的源脚本会先审查提交、备份 GitHub，再交付副本。相同配置再次安装可复用；不同配置或端口被其他进程占用则拒绝覆盖。启动日志不可直接粘贴，它可能包含节点地址。

脚本全部 PASS 后，若管道未在运行，再同步代码：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
bash scripts/git/sync_pull_ff_only.sh
```

同步仍要求干净 `main` 和仅快进，仍不允许服务器向 Public origin 推送。若有失败，将最后 PASS/FAIL 行发回；不要贴节点配置或完整代理日志。初始化发现代理环境变量、origin 专用代理覆盖或原有 HF 广域代理时会拒绝继续，由助手先检查和保留已有设置，不擅自删除。

## 日常启停和撤销

内核独立脱离 SSH 会话运行，但当前不创建 systemd 服务，也不默认开机自启。服务器重启后手动执行：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
python3 scripts/git/github_only_proxy.py start
python3 scripts/git/github_only_proxy.py status
```

停用时先恢复该仓库的原 Git 设置，再停止自己启动的内核：

```bash
python3 scripts/git/github_only_proxy.py git-disable --repo /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
python3 scripts/git/github_only_proxy.py stop
```

停止时校验 `/proc` 可执行文件和进程启动时间，避免 PID 复用后误杀。恢复若发现用户后来改过相关 Git 键，会拒绝覆盖。不删除私有文件、不动其他代理进程。没有额外授权不将其他仓库或程序接入此个人代理。
