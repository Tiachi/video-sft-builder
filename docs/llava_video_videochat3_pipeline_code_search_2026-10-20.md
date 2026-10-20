> 当前配置与v1流程以 [decisions.md](decisions.md) 为准；本文中的旧默认值、演示模型/数量或历史方案不覆盖最新用户决定。

# LLaVA-Video-178K 与 VideoChat3：数据构造代码二次检索与入口审计

核查日期：2026-10-20。范围：官方公开代码、数据仓库、相关发布记录；没有调用教师 API、处理用户视频、安装训练依赖或运行外部生成脚本。

## 1. 结论及上一轮更正

**LLaVA-Video-178K 的真正数据生成代码找到了，放在 Hugging Face 数据集仓库，而不是 LLaVA-NeXT 的训练代码目录。** 官方同时提供三级 caption、开放问答、选择题生成脚本。上一轮“未核到三级 caption 控制器/中间 schema”的结论是漏查，现予更正。

**VideoChat3 的 Academic2M、LV116K 标注合成生产脚本，在本次扩大检索的公开范围内仍未定位。** 已确认的是训练数据读取管道、模型推理代码、训练配方、成品标注及来源映射。应保留“尚未定位”的证据边界，不据此断言作者从未公开过任何相关代码。

对你的方案，当前最准确的判断是：

```text
仅有 MP4
  → 适配 LLaVA 官方三级 caption 脚本：有代码可用
  → LLaVA 官方 caption-to-QA：有代码，可补种子 QA
  → 视频回看核验：需要补
  → Academic2M 式增强/判定：方法公开，具体生产入口仍未定位
  → LV116K 式片段核验/事件账本/长任务合成：方法公开，具体生产入口仍未定位
  → VideoChat3 外层格式导出：成品和 loader 可参考
```

因此 v1 不必从零重建算法；应以官方脚本为基线，修复运行问题并封装。两个 v2 分支仍需按方法实现或继续取得作者明确的合成仓库。

## 2. LLaVA 官方代码在哪里

固定数据仓库 revision：`6d8c562dc26d70042a0d9704d1cae58c94b89098`。以下链接均固定到此版本。

| 文件 | 实际职责 |
|---|---|
| [gpt4o_caption_prompt/GPT4o_description_prompt.py](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/GPT4o_description_prompt.py) | 原 MP4 → 局部描述、递推摘要、全视频总结；本任务最重要的入口 |
| [caption README](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/README.md) | 运行目录、`meta.json`、输出文件名及三级字段说明 |
| [gpt4o_caption_prompt/meta.json](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_caption_prompt/meta.json) | 视频路径字符串列表的输入示例 |
| [gpt4o_qa_prompt/gen_sft_data.py](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/gen_sft_data.py) | caption → 开放问答（OE） |
| [gpt4o_qa_prompt/gen_sft_data_mc.py](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/gen_sft_data_mc.py) | caption → 选择题（MCQ） |
| [QA README](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/README.md) | 三种生成模式和输入说明 |
| [demonstration_pool.json](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/demonstration_pool.json) / [demonstration_pool_mc.json](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/demonstration_pool_mc.json) | 任务定义和少样本示例；分别核到 17 和 12 个任务维度 |
| [video_captions_examples.json](https://huggingface.co/datasets/lmms-lab/LLaVA-Video-178K/blob/6d8c562dc26d70042a0d9704d1cae58c94b89098/gpt4o_qa_prompt/video_captions_examples.json) | QA 输入样例，8 个视频 ID → caption 的映射 |

```text
LLaVA-Video-178K/                  # HF 数据仓库
  gpt4o_caption_prompt/
    GPT4o_description_prompt.py
    meta.json
    README.md
    <一个示例 MP4>
  gpt4o_qa_prompt/
    gen_sft_data.py
    gen_sft_data_mc.py
    demonstration_pool.json
    demonstration_pool_mc.json
    video_captions_examples.json
    video_captions_examples_large_for_test.json
    README.md
  <正式训练标注与媒体分片>
```

本轮只下载了上述 10 个文本/代码文件，没有下载示例视频。代码快照及 SHA256 见 [采集清单](C:/Users/Tiachi/Documents/Dataset/x_temp/video_pipeline_code_search_2026-10-20/manifest.json)。

## 3. 三级 caption 脚本的真实调用链

以下行号对应上述固定 revision；这是静态读码结果，尚无运行验证。

| 入口/函数 | 行号 | 行为 |
|---|---:|---|
| 模块全局设置 | 约 20–30 | `OpenAI()`、`DATASET_NAME="default"`、输出目录 `./descriptions` |
| `load_video_base64(path)` | 139 | Decord 读视频；按取整后的平均 FPS 做帧索引取模采样；PNG 编码并转 base64 |
| `testVisionOpenaiChatCompletions(...)` | 173 | 调 `client.chat.completions.create`，输入系统提示、文本和多张 `image_url`；产生 L1 |
| `testOpenaiChatCompletions(...)` | 201 | 同客户端，只发送文本；用于递推摘要及最终总结 |
| `save_description_json(...)` | 230 | 写单视频中间 JSON，成功时分开保存三级描述 |
| `prompt_video_description(...)` | 246 | 组合上一摘要及新增片段，调用文本汇总 |
| `process_video(version,path,day)` | 271 | 10 帧一组产生 L1；每到 30 帧做累计摘要；结束时生成/复用最后总结 |
| `__main__` | 文件末尾 | 读取 `meta.json`、固定种子打乱、`Pool(processes=1)` 调度；模型硬编码为 `gpt-4o-2024-05-13` |

注意这里的“10 秒/30 秒”是把约 1 FPS 的帧列表当秒计数。代码使用 `round(video.get_avg_fps())` 与 `i % original_fps == 0`，不依据真实 PTS；29.97 FPS、VFR 等情况下不能视为精确时间标签。

### 3.1 MP4 输入合同

官方 `meta.json` 是字符串列表，不要求已有 caption、QA、字幕或音频标签。下面路径为自拟示例：

```json
["/data/raw/a.mp4", "/data/raw/b.mp4"]
```

README 的入口是切到脚本目录运行 `python3 GPT4o_description_prompt.py`；不是带 `--video-dir` 的完善 CLI。输出目录、数据集名称、模型版本等需改代码或在适配版中配置化。

该链路读取视频帧，不消费 MP4 音轨；它满足视觉输入起步的需求。它实际向教师发送多帧图像，学生训练时仍可引用原 MP4。

### 3.2 中间输出 JSON：三级字段确实公开

输出文件：`descriptions/{DATASET_NAME}_{version}_{video_id}.json`。

成功路径直接调用 `json.dump`，包含以下真实键；文本和数字仅为说明结构的虚构示例，省略了数组内容：

```json
{
  "clip_description": ["片段 1 的描述", "片段 2 的描述"],
  "summary_description": ["中途累计摘要"],
  "video_description": "全片总结",
  "completion_tokens": [],
  "prompt_tokens": [],
  "total_tokens": [],
  "prompts_system": [],
  "prompts": []
}
```

实际 token/prompt 数组逐调用记录，并非应当为空；这里仅展示键及类型。失败保存分支没有 `video_description`，因此消费者必须区分完成与部分结果。

三个层级的真实对应关系：

- `clip_description = ret`：L1 列表，约每 10 秒一个。
- `summary_description = sum_ret[:-1]`：L2 **中途**累计摘要，包含前缀上下文，并非互不相交的每 30 秒摘要。
- `video_description = sum_ret[-1]`：L3。最后一次汇总从 L2 列表中移出，作为全视频总结。

这意味着 **30 秒视频通常有 3 个 L1、0 个中途 L2、1 个 L3**；60 秒通常有 6 个 L1、1 个中途 L2、1 个 L3。不能要求所有短视频的三个字段都具有非空列表，也不能额外重复计算一次独立 L3 调用。

令 `N` 是实际采样帧列表长度，非空、无重试的成功路径有：

```text
视觉 L1 调用数 = ceil(N / 10)
全部文本汇总调用数 = ceil(N / 30)
中途 L2 条数 = ceil(N / 30) - 1
L3 条数 = 1
总调用数 = ceil(N / 10) + ceil(N / 30)
```

若 `N≈D秒`，60 秒约 8 次、180 秒约 24 次、1 小时约 480 次。上一轮报告的 9/25/481 对应另一种额外独立 L3 设计，不能作为此官方脚本的次数。次数不是费用；视觉输入与文本输入成本需分别计量。

原始 JSON 不保存视频路径、真实时间戳和事件边界；ID 主要靠文件名关联。适配版应保留原始输出，并另加可追溯元数据，不能把列表下标当精确动作发生区间。

### 3.3 已明确发现的适配问题

| 问题 | 静态证据与影响 | 首版处理建议 |
|---|---|---|
| 未定义全局变量 | 第 24 行 `SAVE_FRAME_SAVE_PATH_ROOT` 被注释，第 142 行仍引用；进入取帧即可能 `NameError` | 去掉无用依赖或显式配置 |
| 凭据配置易误解 | 顶层写了占位 `API_KEY`，但客户端是无参 `OpenAI()`，没有使用该变量 | 客户端显式配置或使用后端支持的环境变量；勿在代码写密钥 |
| 脆弱的模型输出解析 | 多处字符串切分 + `ast.literal_eval`；异常进入 `pdb.set_trace()` | 结构化输出、JSON schema、有限重试和失败隔离 |
| 恢复逻辑缺陷 | `promtps_system` 拼写错误；恢复时没有正确恢复 `prompts_system` | 修复并用故障注入验证恢复路径 |
| 时间轴不精确 | 平均 FPS 取整、全帧遍历，再按索引选帧 | 用真实 PTS 采样，保存取帧时间 |
| 长视频资源成本 | 全视频帧迭代，采样后的 base64 集中存在内存；完成状态检查在解码之后 | 先检查状态，按窗口有界解码/编码 |
| ID 与持久化 | `basename.split('.')[0]` 可导致同名/多点文件名冲突；直接 `w` 覆盖 | 稳定媒体 ID、不可覆盖 staging、原子发布 |
| 错误日志不是真 JSONL | `_error.jsonl` 写 `video_id:response` 文本行；无完整结构化错误合同 | 另写规范错误记录，不按扩展名假定格式 |
| 边界与异常 | 缺少 `sys` 导入却在缺文件分支使用；空视频/部分恢复可能使 `cur_end_time` 未赋值 | 输入预检与边界用例；单视频失败不拖停全批 |

这些是“官方研究脚本需要工程化”的具体理由；不影响其作为三级生成算法基线的价值。三份 Python 文件均通过本轮 AST 语法解析，但**语法通过不等于依赖/API/运行通过**。

## 4. QA 代码的输入、输出及模型接入

### 4.1 输入不是 MP4，也不是三级 JSON 原文件

`gen_sft_data.py` 与 `_mc.py` 读取一个字典：

```json
{"a":"视频 a 的详细 caption", "b":"视频 b 的详细 caption"}
```

键不带文件扩展名。需要增加一个很薄的桥接器：扫描**已成功**的单视频输出，保留 ID 对应关系，将 `video_description` 映射到这个字典。若选择拼接 L1 或引入时间戳，则属于项目自定义扩展，应记录输入版本。

### 4.2 实际生成逻辑

| 模式 | OE | MCQ | 当前入口状态 |
|---|---|---|---|
| `free_form` | 根据 caption 自由生成约 5–10 个不同维度 QA | 约 5 个题，每题 3–5 个选项 | 主流程启用 |
| `icl_once` | 从任务定义和 demonstrations 组织提示，每维度请求一个 QA | 相同机制，输出题干、选项、答案 | 主流程启用 |
| `icl_polling` | 逐任务询问是否适合生成，不适合可返回 `Question=None` | 代码含相应分支 | 主执行块被注释，README 也说当前版本未使用 |

本轮解析的 OE 示例池有 17 维，包括 temporal、spatial、causal、count、fine-grained-action-understanding、time-order-understanding、camera-direction、speed、attribute-change 等；MCQ 示例池有 12 维。这是很有价值的任务体系和 few-shot 素材，不代表任意视频都具备 17 类可答证据。

模型接入位于 OE 第 112 行、MCQ 第 116 行的 `testOpenaiChatCompletion`：`client.chat.completions.create(model=version, messages=...)`。硬编码型号同为 `gpt-4o-2024-05-13`；只发送系统与用户文本，不发送帧、不读音频。**代码生成的 QA 与 caption 一致，不代表与原视频事实一致。**

### 4.3 中间结果不是训练 conversations

OE 的单视频成功文件结构如下，文本为自拟示例：

```json
{"a":[{"Dimension":"temporal", "Question":"What happens after pouring water?", "Answer":"The person stirs the cup."}]}
```

MCQ 多出 `Options` 字段；提示中的选项通常表现为带换行的文本，不应假定为严格的字符串数组。官方 MC 提示还出现 `"Options", ...` 的错误格式示意，适配时应修正提示并强校验，不能依赖模型自行修复。

合并函数将每个成功文件对象 `append` 到列表，因此汇总文件形状是：

```json
[{"a":[{"Dimension":"temporal","Question":"...","Answer":"..."}]}, {"b":[{"Dimension":"count","Question":"...","Answer":"..."}]}]
```

实际脚本把输出根设成 `./saves/{输入文件stem}`。以输入 `captions_v1.json` 为例：

```text
saves/captions_v1/
  free_form/success/<video_id>.json
  free_form/error/<video_id>.json
  free_form/generated_free_form.json
  icl_once/generated_icl_once.json
  free_form_mc/generated_free_form_mc.json
  icl_once_mc/generated_icl_once_mc.json
```

README 的简化路径省去了这一层输入 stem；实现时以代码为准。还需另写 exporter，将上述中间产物转换成所需训练格式。它不是直接输出 LLaVA 发布数据的 `conversations`，也不是 VideoChat3 的 `messages`。

### 4.4 QA 脚本不能直接大批量照跑的原因

两份代码都把 `--num_of_query=-1` 解释成 `len(video_captions)-1`，会漏掉最后一个视频；单视频输入会处理 0 条。须先修复。

成功文件的存在检查发生在模型调用之后，重新运行仍可能先花一次请求再跳过写入；错误重试使用 `while len(error_dir)>0`，持续失败可能无限重试。另有大量易碎解析、固定 `max_tokens=1024`、创建进程池但正常主循环直接同步调用等问题。应先修复重入、限次重试、输出长度与解析，不能把 `NUM_TASK=8` 理解为正常路径已实现 8 路并发。

## 5. VideoChat3：本轮究竟查到了什么

### 5.1 可核实的公开入口

| 位置 | 内容 | 能否生成新的 Academic2M / LV116K 标签 |
|---|---|---|
| [MCG-NJU/VideoChat3](https://github.com/MCG-NJU/VideoChat3/tree/015f52eb2ea70b5abda30192aee18034f2c5f13b) | 官网、demo、训练、评测 | 未定位合成入口 |
| [xtuner-videochat3/README.md](https://github.com/MCG-NJU/VideoChat3/blob/015f52eb2ea70b5abda30192aee18034f2c5f13b/xtuner-videochat3/README.md) | 训练环境、checkpoint 初始化、stage0–3、launchers、媒体和标注路径 | 读取已有标签训练 |
| [xtuner/v1/datasets/vlm_jsonl.py](https://github.com/MCG-NJU/VideoChat3/blob/015f52eb2ea70b5abda30192aee18034f2c5f13b/xtuner-videochat3/xtuner/v1/datasets/vlm_jsonl.py) | JSONL dataset loader；tokenize 和训练打包 | 否 |
| [Academic2M](https://huggingface.co/datasets/MCG-NJU/VideoChat3-Academic2M/tree/fb79513cbbbaf402d321926ce9227f066d774746) | 改写后的成品 caption/QA、媒体/映射、README | 此快照未见合成代码 |
| [LV116k](https://huggingface.co/datasets/MCG-NJU/VideoChat3-LV116k/tree/e32b78d3eb5ac5d1bf28b55a2ba295e99432be62) | 长描述、QA、定位等成品、媒体/映射、README | 此快照未见合成代码 |
| [Training-Data-Annotations](https://huggingface.co/datasets/MCG-NJU/VideoChat3-Training-Data-Annotations/tree/35482967a67d9a3c9b485261dc3b9e2b49cb3932) | 全阶段训练清单、各数据集标注、来源路径表 | 此快照未见合成代码；`training_pipeline.jpg` 是图，不是脚本 |
| [Stage3-Training-Data](https://huggingface.co/datasets/lmwang/VideoChat3-Stage3-Training-Data/tree/a7def4abd394697856be9cd6276efa98a27f23df) | stage3 抽样后的便捷训练发行版 | 此快照未见合成代码；注意作者命名空间是 `lmwang` |
| [VideoChat3-4B 模型仓库](https://huggingface.co/MCG-NJU/VideoChat3-4B/tree/9f6107bdfee9686dfe493444022f5cf79a1a6acf) | modeling、processing、推理/demo | 可作为普通推理后端；未见 Academic2M/LV116K 批量合成编排 |

训练 README 中的 “model and data pipeline” 对应 `JSONL → messages → 媒体处理/tokenization → labels/训练`。用户需要的是 `MP4 → 新标签 → 判定/筛选 → JSONL`。两条链路的输入输出不同，前者不足以证明后者已公开。

### 5.2 扩大检索范围与边界

本轮在上一轮固定主分支文件树、论文方法、真实标注抽样基础上追加了：

1. **GitHub 分支、tag、release**：API 仅返回 `main`，没有 tags、没有 releases。
2. **40 条公开提交及逐提交变更清单**：没有找到以数据合成为职责的 Academic2M/LV116K 入口。三次大型提交的文件列表达到 300 条，存在 API 截断，故另取这三次提交的完整递归文件树：839、2,562、2,565 条，均 `truncated=false`。这补足了文件名排查，不等于逐行审计历史全部内容。
3. **官方 HF 额外仓库文件清单**：Training-Data-Annotations 335 个条目；Stage3 259 个条目；OL617k 4,135 个条目。筛查 `.py/.sh/.ipynb/.zip` 及 prompt/pipeline/script 路径；没有出现目标生产脚本。仅下载小型文本，未展开大型媒体归档，不声称穷尽归档内部内容。
4. **官网资源链接**：链接返回官方 GitHub/HF collection，未发现独立的 annotation-generation 仓库入口。
5. **三位代码贡献者的公开仓库清单**：`leexinhao` 7 个、`zyuhan1999` 85 个、`ZZQ987` 13 个；对相关 `leexinhao/xtuner-videochat` 进一步取得 1,747 条完整文件树，未定位上述数据合成器。未逐行检查所有作者的全部其他项目。
6. **Academic2M/LV116k HF discussions**：各只返回一条 Parquet 机器人讨论，未提供合成脚本入口。前轮 GitHub issues 的已读内容也没有给出相关入口。
7. **全网交叉搜索**：以项目名、数据集名及 generation/synthesis/pipeline/script 组合检索；命中以论文、官方训练入口和数据卡为主，未找到可核实的独立官方生成仓库。二手文章“全管道开放”的概述没有作为代码存在的证据。

一次 Stage3 API 初查误用了 `MCG-NJU` 命名空间返回 401；随后依据官方链接改查 `lmwang` 并成功。这个 401 不能解释成真实 Stage3 仓库受限或不存在。

完整原始响应、版本、URL/SHA256 保存在 [expanded_manifest.json](C:/Users/Tiachi/Documents/Dataset/x_temp/video_pipeline_code_search_2026-10-20/expanded_manifest.json)；汇总见 [expansion_summary.json](C:/Users/Tiachi/Documents/Dataset/x_temp/video_pipeline_code_search_2026-10-20/expansion_summary.json)。

### 5.3 仍缺哪些具体代码

Academic2M 缺的是：已有 QA/caption 的组装器、视觉证据化改写提示与请求编排、原答案一致性 judge、筛选阈值/重试/发布逻辑。仅有你的 MP4 时，还需先产种子 QA；本轮找到的 LLaVA QA 代码可以提供这个环节的起点。

LV116K 缺的是：场景切分与片段调度、局部描述生成与辅助判定、跨片段账本聚合、长 QA/时间线任务生成、grounding 专家接入和最终过滤。原 v1 的 L1 可作为局部描述候选，但不自动等价于经过核验的事件账本，更不能提供精确动作边界。

这两段方法可参见 [VideoChat3 论文 §3.2–3.3](https://arxiv.org/html/2607.14935v2)。本轮没有确认一套能直接“接 v1 JSON、输出两种 v2”运行的官方框架。

## 6. 更新后的实施判断

| 环节 | 当前可复用程度 | 实施难度判断 |
|---|---|---|
| MP4 → LLaVA 三级 caption | 算法、提示、编排与原始输出均找到；需修复和封装 | 小样本研究复现中等；稳定批处理仍中等 |
| caption → OE/MCQ 种子 | 两个官方脚本、示例池和输入输出均找到 | 小样本较低；稳定批处理与有效率控制中等 |
| caption/QA 的视觉核验 | 不在上述 QA 脚本中 | 需新增，中等且决定质量 |
| Academic2M 式增强 | 方法/成品可参考，目标生产脚本未定位 | 中–高，核心是可视证据与答案一致性 |
| LV116K 摘要/时间线/跨段 QA | 方法/成品可参考，目标生产脚本未定位 | 中–高至高 |
| 精确多区间 grounding | 上述 LLaVA 脚本无法提供 | 高，需另行定位模型和边界验收 |
| `conversations/messages` 导出 | 官方成品与 loader 已核实 | 较低；GLM 训练合同需独立适配 |

建议首个实现交付只做 **“LLaVA 官方脚本适配版 + caption-to-QA 桥接 + 独立视觉核验”**，保存原始结果及模型/提示/取帧谱系。先验证 1 个视频不会漏处理、长短尾窗正确、错误可恢复、输出能关联原 MP4，再做小样本盲审。通过后实现两条 v2 方法分支。

这是下一步建议，**本轮没有实现或运行该适配器**。没有充分输入分布和教师服务吞吐，不能把“找到研究脚本”等同于确定的大规模生产工期。

### 决策记录

| 决策 | 证据/状态 | 迁移边界与替代项 | 改变判断的条件 |
|---|---|---|---|
| v1 基于官方 HF caption 脚本适配 | 官方实现已取得并静态核查；AST 通过 | 默认修复并封装；完全重写是替代项，需另证维护收益；未运行 API | 修复后仍无法在代表性 MP4 上可靠恢复/解析，则重构控制器 |
| 用官方 QA 脚本补种子，再视觉核验 | 官方实现只读 caption；这是项目方法迁移建议 | 保留原任务提示但新增核验；直接 VLM 生成 QA 是强替代基线 | 直接视频 QA 在同预算人工盲审中明显更好，则切换或混合 |
| 两条 v2 按方法重建，不假设已有可串联代码 | 当前公开范围检索未定位；未知项明确 | 可等待/取得作者明确入口；也可自行实现并标 inspired | 作者给出合成代码、版本及模型接入合同后重新审计 |

## 7. 核验与交付状态

- 已实施：只读资料采集脚本、检索清单、静态检查与本文；改正上一轮报告的关键错误。
- 已本地验证：下载文件大小与 SHA256、三份官方 Python 的 AST 解析、官方 JSON 示例及 API 响应解析；未 import 外部生成脚本。
- 未运行验证：第三方依赖、付费 API、视频解码、真实模型输出、三级生成或 v2 产出。
- 保存位置：本文在 `docs/`；原始证据在忽略的 `x_temp/`。现有 `.gitignore` 对新 `docs` 文件采取白名单，本轮未修改规则、未提交或推送。

本报告补充并修正 [上一轮完整可行性报告](llava_video_to_videochat3_v1_v2_feasibility_2026-10-20.md)。
