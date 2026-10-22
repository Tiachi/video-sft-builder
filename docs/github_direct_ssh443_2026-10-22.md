# GitHub 拉取优先改用直连 SSH 443

2026-10-22 新证据：用户提供 `modelarts_network_check.sh` v6 原文与服务器输出（UTC 06:06:21，即北京时间 14:06:21）。用户认为代理部署过于复杂，当前只要解决服务器 GitHub 代码下载问题。因此暂停此前未部署的独立代理方案，优先使用已有网络中已通过检测的 SSH 443。

## 结果应怎样理解

| 用户实际输出 | 能证明的事实 |
|---|---|
| DNS github.com/api.github.com/ssh.github.com PASS | 检测时这些名字能解析；不是“GitHub 全部 DNS 失效” |
| GITHUB_WEB HTTP 000、GITHUB_GIT_HTTPS WARN | 对应 HTTPS 尝试在脚本超时范围内未成功；HTTP 000 不是服务器返回的 HTTP 状态码，不能单凭它断言具体防火墙原因 |
| GITHUB_API_PUBLIC HTTP 200、GITHUB_TOKEN authenticated | API 可达且检测 Token 认证成功；不能据此认为 github.com 的 Git HTTPS 同样可用 |
| GITHUB_SSH443_TCP PASS | 检测脚本取到的 ED25519 主机密钥指纹与其固定的 GitHub 官方指纹一致 |
| GITHUB_SSH443_GIT Tiachi/Jev_Research PASS | 使用脚本指定的该仓库 deploy key，经 `ssh.github.com:443` 成功执行 Git `ls-remote`；尚未验证本项目或测量大包吞吐 |
| PROXY_MODE DIRECT | 该脚本未发现代理环境变量；它不等于审计了全部 Git 配置和 SSH ProxyCommand |
| SUMMARY FAIL=0、RESULT=PASS | 脚本定义的必要路径通过，不表示每个 WARN 已修复或 HF 可下载 |

**结论：现有证据足以先选择 SSH 443 替代 Git HTTPS，不需要先装代理。** 这是传输选择，不是已保证本项目认证/速度全部通过。GitHub 官方说明该入口主机是 `ssh.github.com`，使用端口 443；它仍是 SSH 协议，不是 HTTPS。[官方 SSH 443 文档](https://docs.github.com/en/authentication/troubleshooting-ssh/using-ssh-over-the-https-port)。

本次已读取现有 `scripts/git/sync_pull_ff_only.sh`：它已经允许 `ssh://git@ssh.github.com:443/Tiachi/video-sft-builder.git`，无需为此更改同步代码。仍检查干净 main、祖先关系、仅快进与远端 SHA，且不修改 origin pushurl。

## 服务器手动操作

后续实际进展：用户已在服务器生成本项目专用密钥并提供公钥。助手已通过 GitHub API 登记并回读确认 deploy key ID `167273334`，标题 `ModelArts video-sft-builder readonly 2026-10-22`，`read_only=true`、`verified=true`。仅公钥交给 GitHub，没有收到或上传私钥。服务器实际 Git 读取/同步仍待下面命令验证，不因公钥登记成功而标为已同步。

当前助手经 UU 登录服务器仍超时，以下为交付命令，尚未在本服务器执行。不要部署/上传之前的代理安装包，也不需要改系统 DNS、全局代理或 HF 设置。若当前数据构建仍在运行，先等它完成，不在运行途中同步源码。

先在服务器测本仓库，最多 30 秒：

```bash
cd /mnt/sfs/ltj/project/video_data_pipeline/video-sft-builder
git config --local core.sshCommand 'ssh -i /mnt/sfs/ltj/.modelarts-secrets/github/Tiachi/video-sft-builder/deploy_key_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10'
timeout 30 git ls-remote ssh://git@ssh.github.com:443/Tiachi/video-sft-builder.git refs/heads/main
```

返回一行“提交哈希 + refs/heads/main”后，再改 origin 的拉取地址并同步：

```bash
git remote set-url origin ssh://git@ssh.github.com:443/Tiachi/video-sft-builder.git
bash scripts/git/sync_pull_ff_only.sh
```

`git remote set-url origin` 不会删除之前单独设置的禁推送 `remote.origin.pushurl`。本项目本来就是 Public，但 GitHub 的 SSH 访问仍需有效 SSH 认证；Public 的匿名下载能力对应 HTTPS，不能据此省略 SSH 密钥。

首次未显式指定本项目密钥的测试曾返回 `Permission denied (publickey)`。现在用上述仓库局部 `core.sshCommand` 显式选择本项目专用私钥，不依赖当前 shell 的临时变量，也不更改其他仓库或全局 SSH 配置。如果仍出现 `Permission denied (publickey)` 或 `Repository not found`，先把错误发回，不改 origin。现有报告使用的是 `Jev_Research` 专用 deploy key；GitHub 的 deploy key 绑定单仓库，不能把另一个仓库测试通过直接等同于本项目也获授权，也不擅自复制/重绑其私钥。[官方 deploy key 范围说明](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys#deploy-keys)。

如果提示首次信任主机，核对 GitHub ED25519 指纹 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` 后才接受；不关闭主机校验、不将未经核对的 keyscan 结果直接作为信任依据。[官方指纹列表](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)。

这个变更解决 Git clone/fetch/pull 的传输路径，不意味着 GitHub 网页、Release 二进制下载和 HF 也会自动恢复。此次无需同时解决这些独立路径。
