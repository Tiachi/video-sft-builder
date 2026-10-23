# A7 JSON Object接口前置条件修复

## 已确认的代码缺陷

新benchmark A7英文prompt要求返回若干结构化字段，但漏写`JSON`。适配器同时固定发送`response_format={"type":"json_object"}`。这与阿里云官方接口前置条件不符：消息文本需要包含JSON关键词，否则接口报错。[官方结构化输出文档，使用方式](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

caption、C_GATE、QA生成及旧A7 prompt原本均有该词，因此这些阶段成功不能排除新版A7独有的协议错误。这是已确认的静态缺陷；是否确实解释某个历史失败，还要核对该次消息文本（用户上下文也可能恰好含JSON）与服务端返回记录，不能把所有HTTP错误都归到此原因。

## 小范围修改

| 位置 | 修改 |
|---|---|
| [英文审核prompt](../prompts/benchmark/audit.en.txt) / [中文翻译](../prompts/benchmark/audit.zh.txt) | 明确要求返回一个JSON对象，不修改审核字段、证据标准或task规则 |
| [provider.py](../src/video_sft_builder/provider.py) | 新请求在预留/上传/发送前检查消息是否满足JSON关键词条件；不满足直接报ProtocolError且不发送 |
| provider.py发送异常记录 | 从已知本地HTTP错误格式中保存状态码，并在终端显示；不记录任意异常正文、URL、Key或响应payload |
| [只读诊断脚本](../scripts/inspect_run_failure.py) | 增加历史A7的JSON前置条件核对、后续已保存HTTP状态和本地候选拒绝原因 |

无新API角色、采样、重试或模型调用。A7仍每题一次原片完整视觉＋文本；不改C_GATE、不降低质量标准、不关闭JSON模式。

HTTP失败仍保留unknown_execution和费用预留，不能仅根据状态码推断是否计费；此修复不把HTTP400自动当作“可以免费重试”。非HTTP异常仍安全记录类名；本次没有实现完整的供应商错误体/请求号保存或账单查询能力。

## 如何只读核对历史请求

更新代码后，对显式旧构建运行：

```bash
python3 scripts/inspect_run_failure.py --build /absolute/path/to/existing_build
```

对于未决A7，脚本读取已保存的candidate、video元数据和request_view，按原审核格式重建消息文本，核对system_hash/context_hash。当前prompt已变更时，只从本地Git历史读取该构建记录的commit中的原prompt，并验证文件SHA256。不会联网获取历史、修改checkout或回写构建。

输出中`json_mode_check`：

| 字段 | 含义 |
|---|---|
| status=verified | 原prompt文件与两份消息hash均核对成功 |
| frozen_prompt_has_json | 原system消息是否含JSON |
| frozen_context_has_json | 原user文本上下文是否含JSON |
| violates_json_object_prerequisite=true | 在hash核对成功前提下，两份文本均缺JSON，确认该请求不满足接口条件 |
| status=unavailable/message_hash_mismatch | 不能确认，不根据当前修复后的prompt误判旧请求 |

脚本只输出布尔值、原因码及安全元数据，不打印原题、答案、caption或原消息。历史Git文件最多2MiB，命令超时10秒，revision只接受40位十六进制，asset限定为两份官方审核prompt路径。历史缺失则报告unavailable，不自动fetch。

本地拒绝原因只显示代码自有验证器中的静态错误字面量；动态内容隐去。已有候选、原响应、费用状态不修改。

## 旧运行与恢复边界

这次修改了prompt和provider模块，旧构建与新代码出现资产指纹mismatch是预期保护；诊断脚本可以继续只读检查，但不能直接对旧构建`/run`绕过指纹。不得修改旧fingerprint、清空unknown记录或为排查重复生成整片。

现有`recover`命令仅支持已经结束且全为A1/A2的caption-only源，不适用于含未决A7的运行。本次不提供一个会失败或绕过未决请求的恢复命令，也没有自动创建新付费轮次。需先确认旧请求的具体执行/计费与适用的显式恢复方式。

## 验证与状态

定向13项测试通过：9份实际system prompt均显式包含JSON；缺关键词在零请求/零预留阶段被拦截；修复后的审核及用户显式JSON文本可通过；HTTP400状态被保留且请求仍未决、重复调用不发送；任意错误正文不泄漏；旧消息hash核对成功时可检测缺JSON，hash不符不作结论；本地错误原因脱敏。

完整回归219项：217通过、2项真实FFmpeg环境相关跳过（168.052秒）。本地Git历史读取也确认修复前的benchmark A7 prompt不含JSON；实际某轮是否触发，仍以已保存消息hash核对结果为准。随后对缺失历史revision/异常raw形状做防御处理，重复只读工具8项回归通过。

真实历史响应状态码仍不可从丢失记录恢复，修复后真实API效果尚未验证；这些测试没有付费调用。发现静态缺陷不等同于证明历史请求未计费。
