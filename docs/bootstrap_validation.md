# 初始仓库验证记录

日期：2026-10-20。状态：Locally Verified。测试平台为Windows上的Python与Git Bash，不是目标Linux服务器。

已执行`python -m unittest discover -s tests -v`，7项通过：

- 当前配比、取消A4/A10、reject策略与待定配置合同。
- 远端前进时可快进，并可重复执行。
- dirty checkout拒绝同步且保存用户内容。
- 错误origin拒绝同步。
- 本地领先时拒绝覆盖且保存提交。
- 非main分支拒绝同步。
- 脚本被source时返回错误，调用方shell继续存活。

同步测试的远端是临时本地bare仓库，通过本地URL映射模拟；未访问真实GitHub或媒体/API。初次在Windows受限沙箱内运行时，Git Bash命名对象被阻止；在获准的本地环境运行后全部通过。测试目录在项目ignored的x_temp下，不发布运行产物。

另已检查：配置JSON可解析；导出文档的本地链接无缺失；`source_manifest.json`中的export SHA256与导出字节一致；Git whitespace检查通过。新文件allowlist仅代码、配置模板、文档与测试，无媒体/数据/权重/凭据。

尚未验证：目标Linux环境、服务器GitHub认证/路径、实际API接入、视频读取、caption/QA/CoT/审核生产链路、目标GLM预处理或训练。GitHub私有属性与发布后提交SHA另在实际发布时核验，不在此预先声称。
