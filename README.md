# Video SFT Builder

从原始 MP4 构造纯视觉视频 SFT 数据：预清理 → LLaVA 三级 caption → General/Long 标注候选 → 综合审核后通过或 reject。

**当前阶段：项目设计、配置登记与 Git 同步入口。数据生产管道尚未实现；没有读取用户媒体、调用教师 API 或运行训练。**

## 已确定

- Linux 服务器运行，代码经本私有仓库同步。
- 中文/英文 `3:7`，OE/MCQ `7:3`，MCQ 内部三/四/六选一 `1:7:2`；均为最终通过样本条数的全局目标。MCQ始终单选。
- General与Long均启用，二者之间的配比尚未指定。
- 移除A4补标和A10向量/语义分类API。综合审核最多一次，未通过或证据不足直接reject，不回流修复。
- CoT构造方式继续调研，不在本阶段定案。

## 待读取的配置

[configs/project.example.json](configs/project.example.json) 是设计阶段模板，含有待定/null，**不能据此启动付费或数据构造任务**。MP4目录、派生目录、真实API与凭据配置、预算、首轮范围仍待定。前文`qwen3.8-flash`是演示模型，实际接入尚未确定。

“读取范围”只问是否包含子目录：`root/a.mp4`属于本层；`root/sub/b.mp4`属于子目录。当前保留待定，不自动选择。

## 文档

- [当前决策与配比语义](docs/decisions.md)
- [四模块设计](docs/video_sft_four_module_project_outline_2026-10-20.md)
- [10个MP4演示](docs/video_sft_ten_mp4_qwen38_walkthrough_2026-10-20.md)（假设案例，不是实测/配额）
- [配置清单](docs/video_sft_user_configuration_checklist_2026-10-20.md)
- [12字段存储合同](docs/video_sft_final_json_format_2026-10-20.md)（CoT子结构与监督仍待定）
- [Linux同步说明](docs/server_sync.md)

## 代码同步

在Linux上选定代码父目录后首次克隆：

```bash
git clone --branch main --single-branch https://github.com/Tiachi/video-sft-builder.git
```

私有仓库需要服务器已有GitHub访问权限；不要在命令URL中嵌入token。此命令仅克隆代码/文档，不处理视频。

进入新目录后，后续更新运行：

```bash
bash scripts/git/sync_pull_ff_only.sh
```

同步脚本只接受正确origin、干净的main分支和快进更新；拒绝dirty、错误仓库、本地领先或分叉。它不会安装依赖、自动stash或执行数据生产。

## 本地验证

```bash
python3 -m unittest discover -s tests -v
```

测试只创建临时Git仓库，用本地bare仓库模拟远程；不访问真实GitHub、不调用模型、不读取真实媒体。
