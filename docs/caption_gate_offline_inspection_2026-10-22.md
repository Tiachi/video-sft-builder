# Caption 门禁的离线检查工具

`scripts/inspect_caption_gate.py` 只检查一个明确指定的原 MP4、原 manifest 和拒绝 JSON，不联系模型、不重试构建、不修改原片或账本。源视频 SHA256 和 video_id 必须匹配；输出必须为代码仓库外的新目录。真实参考图、caption、审核原文及案例分析保留私有，不提交本代码仓库。

用途：判断门禁引用的稀疏时间点能支持什么，区分“出现了相反证据”和“该点没有看到所述事件/文字”。一个模型 claim 可混合多件事实，不能把其整体标签当成人工核验结果，也不能用一处误判直接给整个 caption 放行。

它复用 `media.gate_frames` 的时间公式：`index × (duration − 1/fps) / (count − 1)`；并复用生产抽帧的 seek、scale、JPEG 参数。本机重建图不是服务器实际上传图，FFmpeg 版本或供应商 resize 仍可不同。原生视频模型的内部实际采样情况也没有因此被验证。

示例，路径均替换为用户明确选中的私有文件：

```bash
python3 scripts/inspect_caption_gate.py --video /private/original.mp4 --manifest /private/manifest.json --rejection /private/reject.json --output /private/new-inspection --ffmpeg /path/to/ffmpeg
```

可用 `--extra-times 0.5,1.0,12.5` 追加少量重点参考帧。这些帧仅供离线检查，不回送门禁，也不代表新增审核结果。`--frame-count` 必须与待复现的请求配置一致，默认 32，上限 64；额外时刻最多 128 个，单次解码设超时。

拒绝文件可为单行 JSON 或带终端前后缀的粘贴文本。输出 `inspection.json` 和带绝对秒数标签的本地 PNG 联系图。模型标签计数不是人工准确率。

工具解码/制图时可选依赖 Pillow 和 FFmpeg；它不改管道 bootstrap 或标准库运行合同。合成测试不需要这些依赖，覆盖绝对时间公式、视频身份不匹配提前拒绝、输入不改及输出不覆盖。本机已完成这些检查和一次真实 MP4 的本地参考帧生成；不把它称为服务器直接运行验证。

策略保持原合同：C_GATE reject 是合法终态，QA=0；修正拒绝归因不等于自动放行，任何额外模型审核/再生成仍按用户新授权和预算处理。
