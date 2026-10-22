# 经UU实验室跳板与本机Clash恢复服务器Git访问

更新：2026-10-22。目标：解决服务器拉取`Tiachi/video-sft-builder`低速/超时，不改变原视频、构建账本、模型API配置或Public仓库只拉取的约束。

## 结论与当前证据

**方案可行，推荐UU直接映射Linux服务器的SSH端口，再用一条SSH反向转发把本机Clash提供给服务器。** 实验室电脑只承担UU TCP中转，无须先在实验室Windows上安装SSH服务。

这项推荐基于网易官方说明：UU可将远端设备或其可达内网中的TCP服务映射到主控本地端口，目标地址从被控设备的网络视角填写。[UU端口映射官方文档](https://uuyc.163.com/help/20260423/40220_1297526.html)。官方网页已实际读取，HTTP 200。用户完成映射后，已实际通过本机12222以现有密钥登录Linux/root，并验证服务器经反向代理访问GitHub，完整链路通过。

本机已验证：Clash实际运行端口是`127.0.0.1:7897`；通过该HTTP代理访问GitHub返回HTTP 200，约0.404秒。用户指定订阅文件中的`7890`没有监听，不能据订阅文件推断运行端口。只读取了端口等顶层设置，没有输出或复制节点、订阅链接或密码。模型API调用数为0。

## 两条方向不同的链路

```text
建立SSH连接：
本机 127.0.0.1:12222 → UU通道 → 实验室电脑 → Linux服务器:实际SSH端口

服务器拉取GitHub：
服务器Git → 服务器127.0.0.1:17897 → SSH反向转发
         → 本机127.0.0.1:7897（Clash）→ GitHub
```

UU解决本机如何连到服务器；SSH的`-R`解决服务器如何借用本机代理。这里的`-R`目标`127.0.0.1:7897`属于发起SSH的本机，不能在实验室电脑上执行同一条命令后期待它访问家中电脑的Clash。[OpenSSH官方手册](https://man.openbsd.org/ssh)。

12222和17897是推荐预留端口，配置前须确认未占用；服务器SSH端口用现有连接中的实际值，不默认其必为22。

## 配置顺序

1. 在本机UU中选择实验室电脑，打开“更多→端口映射”。目标服务地址填**实验室电脑能访问的Linux服务器IP/主机名**，目标端口填实际SSH端口，本地端口建议12222。不要把目标地址填成本机Clash，也不要在目标为另一台Linux服务器时填实验室电脑自己的127.0.0.1。
2. UU显示映射成功后，在本机Windows PowerShell发起SSH并带反向转发。使用Linux服务器账号登录；本机须能完成该账号的SSH认证，实验室电脑保存的密钥不会自动出现在本机。
3. 在服务器验证代理可用后，仅将本项目的Git origin指向服务器的代理端口，再执行原有快进同步。

示例中的`root`仅适用于现有账号确为root的情况；实际命令待用户提供IP、SSH端口和用户名后确定：

```powershell
ssh -p 12222 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:17897:127.0.0.1:7897 root@127.0.0.1
```

保持这个SSH窗口、Clash和UU端口映射在线；该窗口登录的就是Linux服务器，可直接在其中操作。也可以在已有服务器终端使用同一个服务器代理端口。首次主机密钥按实际服务器身份核验，不关闭SSH主机校验。

在服务器项目根目录，首次尚未拿到新工具时，用进程级代理引导原有同步脚本：

```bash
https_proxy=http://127.0.0.1:17897 bash scripts/git/sync_pull_ff_only.sh
```

该环境变量仅作用于这次同步及其子进程。拉取后配置后续Git访问：

```bash
python3 scripts/git/configure_proxy.py --port 17897
```

若首条仍失败，先检查是否有已有Git代理覆盖环境变量、映射端口或SSH转发失败；不要反复增加超时。只检测已有隧道、不改配置：

```bash
python3 scripts/git/configure_proxy.py --port 17897 --check
```

工具先以25秒上限执行真实`git ls-remote origin refs/heads/main`；通过后才写本仓库`.git/config`中的`remote.origin.proxy`与`http.version=HTTP/1.1`，不改origin URL或禁用push的设置。旧本地值私有备份于`.git/video-sft-proxy-backup.json`，不输出其可能包含的代理凭据；检测失败不落配置。手工改过受管理键时拒绝覆盖。恢复本工具之前的值：

```bash
python3 scripts/git/configure_proxy.py --restore
```

Git配置依据：[Git官方配置文档](https://git-scm.com/docs/git-config)。配置范围仅Git，不设置系统代理或全局HTTP环境，不将国内模型API强制转到该代理。

## 前提、替代路径与验证标准

| 情况 | 处理 |
|---|---|
| 实验室电脑可直连Linux的SSH端口 | 使用上述推荐方案，实验室电脑只做UU中转 |
| 需先SSH登录堡垒机，再到计算节点 | 先确认两层目标与认证；不能直接假设UU目标就是最终节点。可进一步使用ProxyJump，但需具体连接信息 |
| 本机无法认证服务器账号 | 先配置可用的现有密码/授权密钥方式，不自动复制实验室私钥 |
| SSH拒绝远程转发或17897被占用 | 明确失败，不静默改成其他端口或修改sshd；确认可用端口和服务器转发权限 |
| 关闭本机/Clash/UU映射/SSH | 该代理不可用；下次拉取先重建通道。已运行的服务器计算不会因此自动结束 |
| 当前需求仅同步代码 | 仅在拉取时保持通道在线；模型API仍走原来独立配置 |

验收已依次通过：本机Clash公开GitHub请求成功→UU映射SSH认证成功→SSH反向端口可用→服务器代理下ls-remote成功→快进同步成功，首次同步SHA为`8ffd4a6372bed7950151100228aa3e6fb2c00a27`，与当时GitHub main一致。服务器请求GitHub返回HTTP 200，耗时约1.091秒；仓库干净，禁用push URL仍生效。没有启动数据构建、修改旧轮次或调用模型。

## 本机VS Code连接配置

本机新增`audio_1_uu`用于正常登录，`audio_1_proxy`用于独立代理隧道。两者指向UU本地12222、采用现有本机私钥；已接受的服务器公钥保存到专用known-hosts文件，后续严格校验。原SSH连接项保留，修改前生成带时间的原文件备份；没有复制私钥。VS Code已有Remote-SSH扩展，Linux平台设置只新增这一主机项，原设置和注释保留。

在VS Code按`Ctrl+Shift+P`，选择`Remote-SSH: Connect to Host...`，选`audio_1_uu`。配置后已用此别名实际SSH登录验证；未声称已经打开VS Code图形远程窗口或完成首次VS Code Server安装。[VS Code官方说明](https://code.visualstudio.com/docs/remote/ssh)。

代理隧道独立后台运行，因此关闭或重新连接VS Code不会争抢17897。重启本机或隧道退出后，可在本机PowerShell运行`ssh -N audio_1_proxy`重建并保持该窗口运行。仅VS Code登录不配置RemoteForward，避免多个编辑器连接同时申请同一端口。UU映射需保持在线，Git代理还依赖Clash和隧道进程。

本地设置实现为`scripts/git/configure_uu_vscode.ps1`：仅在所有输入/冲突检查通过后写入已备份的SSH/VS Code配置，保存原连接和无关设置；重复执行不重复追加，发现人工修改或别名冲突则拒绝覆盖。该脚本不连接服务器、不启动GUI、不复制私钥、不改变系统代理；需要一份已通过SSH接受的公钥记录作为seed。

## 工具验证记录

本次8项代理工具测试全部通过，覆盖配置/重入/恢复、探测失败不写配置、只读检查、人工修改保护、错误仓库/端口拒绝、原代理值私有保留及main响应格式校验。原同步脚本7项本地回归通过。Windows SSH/VS Code设置新增3项合成隔离测试通过，覆盖原文件备份/保留/重入、别名冲突和自定义配置拒绝；真实本机别名解析、SSH登录及服务器网络/同步均实际验证。改动仅涉及scripts、docs和tests，未改生产模块/模型prompt/构建配方，不额外改变生产代码资产指纹。
