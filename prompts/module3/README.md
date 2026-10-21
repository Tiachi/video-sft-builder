# 模块三完整prompt草案及中文翻译

日期：2026-10-21。**本目录六份文本均为本项目新写的完整草案，尚未经过真实模型试产；不是LLaVA或VideoChat3官方prompt。** 英文是拟用于请求的原文，中文是逐段对应译文。选择一套语言发送即可，不把中英两套同时堆进请求。输出语言仍由每个slot的language决定，英文system也能要求生成中文问题。

| 用途 | 英文原文 | 中文翻译 |
|---|---|---|
| General system | [general.system.en.txt](general.system.en.txt) | [general.system.zh.txt](general.system.zh.txt) |
| Long system | [long.system.en.txt](long.system.en.txt) | [long.system.zh.txt](long.system.zh.txt) |
| 两分支共用user | [user.en.txt](user.en.txt) | [user.zh.txt](user.zh.txt) |

`{{payload_json}}`是程序对完整请求对象做JSON序列化后的唯一替换点。模板措辞、task定义、few-shot与caption均位于payload中，不能被当作system级指令。示例prompt不含真实API凭据/模型名；其输入输出合同见[模块三详解](../../docs/module3_general_long_walkthrough_2026-10-21.md)。

官方LLaVA原文入口与核心短句、VideoChat3方法来源/缺失边界均在详解中逐项标明，不将本文草案冒充公开生产prompt。
