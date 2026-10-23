# LLaVA-Video-178K 三级 Caption：论文、原始代码与本项目核查

核查日期：2026-10-23。范围：L1/L2/L3 的输入、输出时间范围、调用顺序及本项目差异。本次仅新增核查文档，不修改生产逻辑、不执行视频推理、不继续旧构建。

## 1. 先回答你的理解

| 层级 | 你的理解／希望 | 原版实际行为 | 判断 |
|---|---|---|---|
| L1 | 当前 10s 视频＋前一条 L1＋最近一条 L2，输出当前 10s Caption | 当前 10s 的采样帧＋**尚未被 L2 汇总的所有前序 L1**＋最近一条 L2，输出当前 10s Caption | 输出范围正确；历史 L1 的选取不完全相同。原版通常带 0、1、2 条，跨 30s 边界时清空这组 L1 历史 |
| L2 | 当前 30s 视频＋前一条 L2＋对应 3 条 L1，输出**当前 30s** Caption | **不输入视频**；最近一条 L2＋新增 3 条 L1，输出**从视频开头到当前时刻**的累计摘要 | 你增加 30s 视频属于主动扩展；将输出限制为当前 30s，则改变了原版的累计摘要设计 |
| L3 | 希望确认原版做法 | 最近一条累计 L2＋其后尚未汇总的 L1，进行**纯文本合并**，输出全视频描述；结尾恰好落在 30s 边界时，最后一次汇总直接作为 L3 | 原版没有统一追加一次全视频视觉调用，也不要求把全部历史 L2 一起重新输入 |

这里必须区分两个概念：**“每隔 30s 更新一次”不等于“输出只覆盖这 30s”。** 原版 L2 在 30s 时覆盖 0–30s，在 60s 时覆盖 0–60s，在 90s 时覆盖 0–90s。视频越长，累计摘要可能变长；这不代表原版需要反复输入越来越长的视频，因为原版 L2 根本不输入视觉内容。[论文 §3.2](https://arxiv.org/html/2410.02713v1#S3.SS2)

## 2. 核查依据与可信范围

### 2.1 原始材料

- 论文：[Video Instruction Tuning with Synthetic Data，arXiv:2410.02713v1](https://arxiv.org/html/2410.02713v1)，重点核对 Figure 2、§3.2。另核对了 2025-08-01 修订的 [v3：LLaVA-Video: Video Instruction Tuning With Synthetic Data](https://arxiv.org/html/2410.02713v3#S3.SS2)，这三层的输入与累计范围描述一致；本结论不依赖仅阅读早期版本。
- 作者公开脚本：[GPT4o_description_prompt.py，固定版本](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py)。该文件在数据集仓库中，不能用 LLaVA 的训练入口代替它。
- 源码版本：`6d8c562dc26d70042a0d9704d1cae58c94b89098`；文件 20,821 字节；SHA256：`e5a0ff525a09638f1b4613a346a94705ab243e8c222139e31a98d629a451de50`。本次读取既有原始文件缓存并重新计算哈希，与此前公开来源清单一致；没有重新执行作者脚本或声称复现了作者生产环境。
- 本项目对照基线：`30fb52d1a7dcc1f6531ff423bf61d6d922112ba9`，重点是 [pipeline.py](https://github.com/Tiachi/video-sft-builder/blob/30fb52d1a7dcc1f6531ff423bf61d6d922112ba9/src/video_sft_builder/pipeline.py#L95) 和 [caption.txt](https://github.com/Tiachi/video-sft-builder/blob/30fb52d1a7dcc1f6531ff423bf61d6d922112ba9/prompts/runtime/caption.txt)。

### 2.2 论文图注与正文的一处简化

Figure 2(a) 图注把 L1 历史概括为“前一个 L1”；但 §3.2 正文写的是“所有最近、尚未汇总进 L2 的 L1”。**实际实现应以正文和脚本共同确认的逻辑为准。** 因此，你对 L1 的理解有图注依据，但不能据此说源码始终只传上一条 L1。[论文 Figure 2 与 §3.2](https://arxiv.org/html/2410.02713v1#S3.SS2)

## 3. L1 到底怎么构建

### 3.1 输入和输出

作者脚本先按约 1fps 抽帧，再每 10 张采样帧处理一次，名义上对应 10s。**作者发送的是图片序列，不是原生 MP4 视频字段。** 第一个片段使用 `first_clip_system`；后续片段使用带历史的 `other_prompt_system`。

核心代码位置：[原始脚本 L296–318](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L296)。下面是保持原意的简洁伪代码：

```python
for current_10s in sampled_video:
    recent_l1 = L1_since_last_summary  # 当前 30s 分组中，已完成的 0/1/2 条
    history = [latest_cumulative_L2_if_any] + recent_l1
    current_L1 = VLM(current_10s_frames, history)
    save(current_L1)                  # 只描述当前 10s
```

源码对应变量是 `ret`（全部 L1）与 `sum_ret`（已生成的汇总）。`ret[len(sum_ret)*3:cur_start_time//10]` 取出尚未汇总的前序 L1；在 30s 分组起点，`pre_clip_desc=[]`。最近一条 L2 则通过 `sum_ret[-1]` 加入。

### 3.2 用名义 60s 视频说明历史怎么带

以下为整齐的 10s/30s 窗口示意，不代表所有实际 MP4 的采样帧数都恰好等于标称秒数。

| 当前 L1 片段 | 原版传入的历史 L1 | 原版传入的 L2 | 当前输出范围 |
|---|---|---|---|
| 0–10s | 无 | 无 | 0–10s |
| 10–20s | L1[0–10] | 无 | 10–20s |
| 20–30s | L1[0–10]、L1[10–20] | 无 | 20–30s |
| 30–40s | 无 | 累计摘要[0–30] | 30–40s |
| 40–50s | L1[30–40] | 累计摘要[0–30] | 40–50s |
| 50–60s | L1[30–40]、L1[40–50] | 累计摘要[0–30] | 50–60s |

**对你的 L1 方案的评价：可以实现，但属于简化变体。** 只带前一条 L1 会少带本组更早的细节；在分组起点又会额外重复携带一条已经进入 L2 的旧 L1。是否值得这样改，需用实际字幕/人物/事件连续性评估，不能仅凭输入更少就断言质量不变。

推荐默认保留原版“最近累计摘要＋未汇总 L1”的历史选择方式；如果采用你提出的局部 L2，则须重新理解这份历史的覆盖能力，见第 7 节。

历史只用于消歧与连接叙事，不能当作当前片段确实出现某事的视觉证据。原始 `other_prompt_system` 已提醒：前面出现的人物、物体、场景，不一定仍在当前片段中。[原始提示词 L84–109](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L84)

## 4. L2 到底怎么构建

原版每处理完 3 个 L1，调用文本汇总函数。假设 `S30` 表示覆盖 0–30s 的累计摘要：

```text
S30 = 文本模型(L1[0–10], L1[10–20], L1[20–30])
S60 = 文本模型(S30, L1[30–40], L1[40–50], L1[50–60])
S90 = 文本模型(S60, L1[60–70], L1[70–80], L1[80–90])
```

这不是仅对最近 30s 做摘要，而是用上一次累计摘要保留更早的内容，再并入新增片段。代码依据是 `cur_desc = [sum_ret[-1]] + clip_desc`，随后调用 `prompt_video_description`；该函数调用的是**纯文本** `testOpenaiChatCompletions`，而非视觉函数。[汇总触发 L340–349](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L340)、[文本汇总函数 L246–268](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L246)。

**你希望的 L2 有两个独立改动：**

1. 增加当前 30s 视频：可以用视觉信息补充、核对当前分组的 L1；属于合理的工程扩展，但增加一次当前分组的视觉输入，不能保证完全消除幻觉。
2. 输出只覆盖当前 30s：同样可行，而且时间归属更清楚；但它不再承担原版累计记忆的作用，必须配套调整 L3 和下游取 Caption 的方式。

因此不能把“只发送当前 30s 视频”自动解释为“文本也只覆盖当前 30s”。当前视频可以只覆盖本组，而文本仍是累计摘要；本项目现在就是这样实现的。

## 5. L3：原版如何收尾

### 5.1 不是统一再看一次视频

原始 L3 仍通过 `prompt_video_description` 进行纯文本合并，输入是：**最近累计 L2＋之后尚未汇总的 L1**。更早的 L1 已经被压进最近累计 L2，不再逐条重复输入。

脚本没有单独定义一套全视频视觉 L3 提示词，也没有在这一步稀疏抽帧审核。你项目里的 C_GATE 是额外审核环节，应与原版 L3 生成分开理解。

### 5.2 两种结尾情况

**情况 A：结尾恰好落在 30s 汇总边界。**

例如名义 60s：完成最后 3 条 L1 后，用 `S30＋L1[30–40]＋L1[40–50]＋L1[50–60]` 做最后一次汇总，直接得到全视频描述。**不会先产一条 S60，再额外调用一次模型把 S60 改成 L3。** 该次调用设置 `last_time_summarize=True`。[原始脚本 L340–349](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L340)

**情况 B：结尾不在 30s 边界，存在尚未汇总的尾部 L1。**

例如名义 70s：先有 S30、S60；得到 L1[60–70] 后，执行 `文本模型(S60, L1[60–70])`，得到全视频描述。尾部可能有 1、2 或 3 条 L1，取决于剩余采样帧和分块情况，不能固定说只有最后一条。[原始脚本 L357–361](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L357)

### 5.3 L2 与 L3 是否用了不同提示词

该固定版本中，两者调用同一个汇总函数、同一套 `summarize_prompt_system` / `summarize_prompt`。`last_time_summarize` **没有改变模型收到的提示词**，只控制返回文本的后处理：非最终摘要把其中的小写 `video` 替换为 `clip`；最终摘要不做这次替换。因此不能把原版描述成另有一个复杂、独立的 L3 生成模型或特殊全局提示词。[原始脚本 L246–268](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L246)

### 5.4 为什么原始 JSON 的 L2 数量可能比你想的少

原版成功保存时：

```python
clip_description = ret                  # 全部 L1
summary_description = sum_ret[:-1]       # 中间累计摘要，归为 L2
video_description = sum_ret[-1]          # 最后一次汇总，归为 L3
```

最后一次汇总从 L2 列表中取出，单独保存为 L3。[原始保存函数 L230–236](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py#L230)

| 名义长度／假设采样帧数 | L1 调用 | 文本汇总调用总数 | 成功 JSON 中的中间 L2 | L3 来源 |
|---|---:|---:|---|---|
| 30s／30 帧 | 3 | 1 | 无 | 3 条 L1 的最终汇总 |
| 60s／60 帧 | 6 | 2 | S30，一条 | S30＋最后 3 条 L1 |
| 70s／70 帧 | 7 | 3 | S30、S60，两条 | S60＋尾部 L1[60–70] |

这些计数针对成功、无重试的原始控制流，不含 QA 或项目新增审核。原始脚本按取整后的源 FPS 间隔抽帧，再按帧索引切块；真实 PTS、非整数帧率、末尾不足一秒等情况需要项目自己的时间覆盖校验，不能用本表证明任意实际 MP4 都恰好产生相同数量。

## 6. 本项目当前实际做了什么

本节是对固定项目提交的静态核查，**不是本次服务器运行验证**。

| 环节 | 当前实现 | 与原版关系 |
|---|---|---|
| L1 / A1 | 当前约 10s MP4＋最近累计 L2＋本组已完成的全部 L1 | 历史选择接近原始正文和代码；视觉传输改成原生视频，FPS 由配置决定 |
| L2 / A2 | 当前约 30s MP4＋最近累计 L2＋本组 L1；输出覆盖 0–当前分组末尾 | 增加了本组视频，仍保持累计文本输出 |
| L3 | 保留全部 L2，再把最后一条累计 L2 的内容引用为 L3；无额外模型调用 | 最后累计摘要覆盖全片，因此可作为全片描述；保存结构和原版不同，也没有原版的 `video`/`clip` 后处理区别 |
| C_GATE | 对 L3 进行稀疏视频审核，按当前重大视觉不符政策决定通过／拒绝 | 项目额外环节；不属于作者的 L3 合并调用 |

关键代码证据：

- [A1 历史输入：pipeline.py L102–105](https://github.com/Tiachi/video-sft-builder/blob/30fb52d1a7dcc1f6531ff423bf61d6d922112ba9/src/video_sft_builder/pipeline.py#L102)。
- [A2 输入与累计输出：L125–133](https://github.com/Tiachi/video-sft-builder/blob/30fb52d1a7dcc1f6531ff423bf61d6d922112ba9/src/video_sft_builder/pipeline.py#L125)：`cumulative_text_range.start=0`，保存记录也以 0 为起点。
- [L3 引用最后累计 L2：L137–139](https://github.com/Tiachi/video-sft-builder/blob/30fb52d1a7dcc1f6531ff423bf61d6d922112ba9/src/video_sft_builder/pipeline.py#L137)。

所以，**你现在描述的“局部 30s L2”并不是当前代码已经实现的行为。** 此前若把本项目 L2 讲成只覆盖当前 30s，应以本次核查纠正；当前 30s 是视觉窗口，累计范围是文本窗口。

## 7. 如果采用你希望的局部 L2，需要怎样衔接 L3

你的设计可以成立，但需要明确成为“局部 L2＋独立全局合并”的项目变体：

```text
各 10s 片段 → L1（输出仅限该片段）
每组 3 个 L1＋对应 30s 视频＋前一局部 L2 作上下文
    → 局部 L2[0–30]、局部 L2[30–60]、局部 L2[60–90]……
全部局部 L2，必要时附带 L1 细节
    → 单独的全局文本合并 → L3[0–全片结束]
L3＋稀疏视频 → C_GATE
```

这里有三点不能遗漏：

1. **L3 不能再直接引用最后一条 L2。** 否则 1 小时视频的 L3 将只描述最后约 30s，构成语义上的静默截断，即使所有视频切片都完整存在。
2. **只给 L1 提供前一个局部 L2，无法保留很久以前的全局记忆。** 它可以支持邻接片段连续性，但不能假定早期人物、对象、主题仍已完整传入。若需要跨很久的身份连续性，应另设累计记忆；这会成为额外设计，不能偷偷把局部 L2 又写回累计摘要。
3. **下游必须保留访问全片 Caption 的能力。** 当前 QA 上下文使用全部 L1、最后一个 L2 与 L3；如改成局部 L2，应明确是否把全部局部 L2 一起交给 QA，而不是沿用“最后一个就代表全片”的假设。全局合并遇到上下文／预算限制要显式 blocked，不能悄悄丢掉前面的分组。

### 建议与状态

- **来源核查结论已明确：** 原版采用累计 L2；当前项目也采用累计 L2，并额外输入当前 30s 视频。
- **推荐的最小改动默认：** 若继续沿用原版，只需纠正文档中的时间范围表述；保留当前 A1 历史选择和累计 L2，不增加 L3 调用。这不能声称与作者运行结果完全等同。
- **若优先满足你本次提出的局部 30s 输出：** 采用“局部 L2＋独立全局 L3 文本合并”；L1 默认仍建议带当前组未汇总的全部 L1。相较当前项目，每个视频通常增加一次 L3 文本调用，另需核算全局合并上下文；不增加全片视觉重读。此方案是建议，**尚未实施**。
- **质量判断边界：** 局部 L2 可减少反复改写更早文本，但独立 L3 仍可能压缩遗漏；累计 L2 可节省每次历史输入，却可能累积遗漏或错误。两者谁更适合你的长视频、学术视频，需同视频对照，现有静态证据不足以保证质量收益。

本次没有修改配置、提示词、调度、缓存或费用记录，也没有替换任何已构建的 Caption。
