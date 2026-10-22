# 三管线参考库：本地验证与交付边界

日期：2026-10-22。代码基线：`266ffdda6d98bd8296bd48b776ea3edf62e83e41`，在该基线上新增离线工具、聚合文档、排除清单并更新设计入口；最终Git提交由交付记录给出。未修改运行pipeline、schema、prompt、API配置或真实构建目录。

## 已验证

- `tests/test_three_branch_references.py`：9项通过。覆盖源选项数/答案映射、OE空选项占位、缺额外图片/计数/时间筛除、干扰项不误作音频依赖、Markdown转义、视觉问题排序、跨分支源身份、缺题不借类补造/不重复、输出隔离。
- 官方固定revision的7个标注文件：校验已记录大小与Git/LFS内容摘要后读取，总计9349道独立源QA。Video-MME long另作子集视图，LVBench保留多标签。
- Video-MMMU Adaptation：141个Case Study Analysis与159个Problem-solving Adaptation均有非空image bytes及path，未导出图片或将其伪装成MP4中的画面。
- 最终导出`qa_reference_three_branches_20261022_v3`：`--validate-only` PASS；11个导出文件内容摘要、完整选样回放、96分类、726行/695原题、原题选项/答案、CSV和Markdown一致性均通过。v3额外排除31个Video-MMMU概念候选中的符号结构/知识捷径等问题，固定总数不变；69条附加排除有ID与原因记录。
- 条件保留75组：70组各10题，5组不足；21组整类暂缓。General307、Long142、Knowledge277行。外置manifest记录22道跨分支共享题、总计31次重复来源出现。
- 本次模型调用0、网络数据下载0；没有视频解码、服务器运行、GLM processor验收或修改旧产物。

## 未验证/不能推断

- 没有观看benchmark视频或构造其caption；静态规则会漏过隐式对白、细微视觉、公式/图表及主观答案问题，也会保守误杀部分本可做的题。不能把参考库标为“已验证caption可答”。
- 原标注答案原样保留。提取一致性PASS不证明原答案正确；发现疑似错标按ID排除，不代替数据方改答案。
- 参考库没有作为生产few-shot载入；新Knowledge管线、新能力task及Long单段检索审计尚未实现。没有新的真实生成质量或费用证据。
- 用户首轮不安排人审，未进行用户/领域专家人工审阅，不能给出准确率、错误接受率或专家背书。

## 可复现性与存储

输入：`C:/Users/Tiachi/Documents/Dataset/x_temp/benchmark_nonvideo_20261022`，原标注只读。输出：同级`qa_reference_three_branches_20261022_v3`，不在Public代码checkout内；早期review与旧版导出保留，不覆盖。

完整来源revision、输入/输出SHA256、脚本SHA256、排除清单SHA256在外置`manifest.json`。代码仓库仅提交脚本、微型合成测试、ID/原因清单和96组聚合计数，不提交原标注、QA表或图片。

本地聚合JSON与外置`category_summary.json`内容一致（Git可能规范化行尾）；Markdown在相同计数表前增加口径说明。来源与方法限制见[设计说明](three_branch_caption_qa_design_2026-10-22.md)。
