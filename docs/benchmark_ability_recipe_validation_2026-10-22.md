# benchmark_v1 实现验证记录

日期：2026-10-22。仓库 `Tiachi/video-sft-builder`，稳定分支 main。修改基线 `7805be6616ebeb24b6052b85e3cfea3b43255678`。本记录只描述本地代码/合成测试；没有下载新视频、调用付费模型、修改原片或已付费旧运行，也没有部署服务器。

## 检查结果

| 检查 | 结果 | 实际证明的范围 |
|---|---|---|
| 全套 unittest discover -s tests | **204 项：202 通过，2 跳过**，156.370s | 新三分支、旧两分支回归、预算与失败保护、合成/localhost协议等 |
| 跳过项 | 本机未安装可执行的真实 FFmpeg/ffprobe | bootstrap 实媒体自检及真实切片集成未在本机复验；模拟FFmpeg兼容测试仍通过 |
| build_benchmark_recipe.py --write，随后无参数漂移检查 | PASS | 32任务、256双语模板、96来源类映射与编译器一致；再次更新自有资产使用显式原子替换 |
| validate_design.py | PASS | 旧两分支设计作为兼容夹具保留，并指向新recipe合同；不是新方案质量证明 |
| pyproject data-files存在性检查 | PASS，17个已声明打包资源均存在 | 新任务/模板/映射与中英prompt被声明；不是独立安装环境集成测试 |
| git diff --check | PASS | 无patch空白错误；不是语义正确性证明 |

## 有意义的边界与故障测试

- 逐项构造32个任务全部合法OE/MCQ形式，检查operation/证据角色合同。
- 错操作标签、同事实重复充角色、重复claim、缺视频前提、冒充expert_verified来源，均本地拒绝。
- 每个普通MCQ错误项须有允许的错误类型及证伪依据；打乱后字母与元数据一致。
- 排序事件必须绑定真实引用fact，3/4/6单选程序产生互异排列，事件E编号与外层A字母分离。缺排序结构或伪造事件文本被拒绝。
- 定位使用现有窗口，OE缺正确TIME引用拒绝；不足3/4/6窗口的MCQ组合调度前排除，不产生付费请求。
- A7缺能力检查或视频必要性/规则适用性/operation为insufficient时拒绝；单段Long检索合法，跨段事实越界仍拒绝。
- caption gate拒绝则三分支全不执行；Knowledge质量拒绝不补题；生成前判task不适合可依次尝试，6任务穷尽后停止，没有无限文本重试或A7。
- 既有私有设置没有qa_recipe时不迁移、不自动改写；显式选择后才能为新构建编译新recipe。未知recipe或Knowledge缺尝试上限不通过配置检查。
- 三分支完成记录独立校验；删除Knowledge终结记录会得到incomplete。重复运行复用已完成响应，不新增调用。
- 最终记录仍只有12字段、cot=null；assessment/专业规则等仅sidecar。导出证据sidecar篡改会触发拒绝覆盖。

## 合成端到端证据

输入是测试用30s与60s两份**不可播放的合成占位文件**，由SyntheticMedia/SyntheticProvider适配；不是用户真实视频，也不是可训练内容。

| 方案 | General候选通过 | Long候选通过 | Knowledge候选通过 | 模拟调用 |
|---|---:|---:|---:|---:|
| legacy_v1回归 | 10 | 6 | 不启用 | 44 |
| benchmark_v1 | 10 | 6 | 10 | 62 |

新方案62次按角色：A1=9、A2=3、C_GATE=2、A3=16、A5=6、A7=26。按分支账本：共享caption14、General18、Long12、Knowledge18、未归属0；分支费用之和等于总使用量计费结果。模拟器固定token仅供预算账本测试，不能用于推算真实Qwen/vLLM费用。

通常单视频为n1+n2+25，默认保守尝试上界n1+n2+43；A3同时承接General与Knowledge，因此报告依据branch而非仅role拆账。Knowledge不会重新生成caption。

## 尚未验证

真实模型是否遵循复杂协议、拒绝/适配率、专业规则正确率、任务真实难度、问法与答案多样性、给定源视频的有效Knowledge产率、学生processor可见证据、训练后benchmark收益均未知。没有安排人审；自动审核候选不是经过专家核验的训练发布。合成器总是按夹具返回检查结果，不能用于证明这些语义质量。

完整设计、任务表、模型调用与启用方法见[实现说明](benchmark_ability_recipe_implementation_2026-10-22.md)。GitHub备份与服务器运行状态分开记录：本地发布不代表服务器已经同步。
