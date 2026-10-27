# Agent 资料整理指南

团队的学习目录使用中文：`实验资料/`、`课程资料/`、`共同知识/`、`周报/`；周报图片放在 `周报/附件/`。

## 共享 Skill 在哪里

[团队资料整理与PR协作](.agents/skills/team-learning-materials/SKILL.md)是团队共同维护的操作说明，约定 Agent 如何整理普通资料、标注来源、检查附件以及准备草稿 PR。

它不包含账号、模型服务或后台任务。Git、GitHub 权限及实际运行环境由各成员自己配置；同伴核对内容后再合并。

`.agents/skills/`、`SKILL.md`、`agents/openai.yaml`和`.github/`是工具识别的技术路径，保留这些名称。Skill 的显示名和正文为中文。

## 怎么使用

在 Codex 中打开本机的团队知识库目录，在对话中选择或输入 `$team-learning-materials`。仓库内技能可以按任务匹配，也可以明确调用。若列表没有更新，重启 Codex 后再检查。

```text
使用 $team-learning-materials，整理我指定的一份普通学习资料：
输入文件：填写实际路径。
目标：说明是实验、课程资料，还是共享笔记。
只处理这些文件，保留原始来源和待核对项。
完成检查后推送独立分支并创建草稿PR，供队友审阅。
```

在其他 Agent 工具中，可以明确要求它读取本仓库 `.agents/skills/team-learning-materials/SKILL.md` 后处理指定资料；该工具是否支持自动发现或技能安装，需要按其自身规则配置。

个人总结或读后感可以使用大模型辅助提供思路、提出问题和组织表达，由本人结合真实阅读与经历修改、确认。普通周报归档保留本人确认原文，不代写其他成员经历。

## Actions 是什么

GitHub Actions 是自动运行任务的平台。运行什么取决于仓库的工作流文件。

参考仓库的[资料校验流程](https://github.com/jry21223/HENU-Final-Review/blob/main/.github/workflows/validate-materials.yml)执行 Node/Python 脚本，检查文件、索引和规则；这部分没有调用大模型。AI 审阅需要另行接入模型或审阅服务。自动检查通过，也不能保证知识内容正确。

本仓库的链接和附件检查由 `scripts/check_docs.py` 与 `.github/workflows/check-docs.yml` 提供。AI 自动审阅另行配置；这套固定检查不调用模型。

## 自动检查和 AI 审阅怎么配置

两者可以配合使用，承担不同任务：

| 方式 | 适合检查 | 需要配置什么 |
|---|---|---|
| 普通 Actions | 文件存在、链接附件、目录和索引一致性等固定规则 | 实际检查脚本，以及 `.github/workflows/` 内的工作流 |
| Codex GitHub 审阅 | PR 改动中的代码问题和符合仓库审阅规则的疑点 | 将仓库接入 Codex，启用 Code Review；可手动或自动触发 |
| 自定义 AI Actions | 按自定义提示词处理 PR，例如指定学习资料的核对范围 | 模型调用、凭据、权限、提示词和发布结果的工作流 |

### 普通 Actions

1. 仓库 Settings → Actions → General，确认允许使用工作流所需的 Actions。只做读取和检查时，工作流权限使用 `contents: read` 即可。
2. 编写适合本仓库的检查脚本，明确失败时返回非零退出码；例如检查正文引用的图片是否随文件上传。
3. 添加 `.github/workflows/资料检查.yml`，设置 PR 触发并执行检查脚本。提交变更后在 PR 的 Checks 或仓库 Actions 页面看本次提交的运行结果。

仅在设置中打开 Actions，不会凭空获得资料检查功能；需要实际脚本和工作流。[GitHub 官方设置说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)。

### Codex GitHub 审阅

在 Codex 中连接 GitHub 并授权目标团队仓库，在 Codex 审阅设置中选择该仓库、启用 Review code。接入后可在 PR 评论中使用 `@codex review`；需要自动运行时，再核对仓库的 Automatic review 和个人偏好的触发设置。

如需长期遵循本团队的审阅重点，可在仓库的 `AGENTS.md` 中维护简短的 Code Review Rules。当前 Skill 文件不等于已经启用 GitHub 自动审阅。[官方 OpenAI 配置说明](https://learn.chatgpt.com/docs/third-party/github)。

通用 Code Review 主要面向代码改动。对于课程笔记和 PDF，需要另行明确检查范围并验证效果，不能据机器人未评论就认定全文正确或每页均已检查。

如果以后需要自定义 AI 工作流，可考虑 `openai/codex-action`；这一路径需要把 API 密钥保存在仓库 Secrets，由工作流引用，不把密钥写进文件。[官方 Action 说明](https://learn.chatgpt.com/docs/github-action)。

### 对本团队的建议与当前状态

先落地链接、附件等固定检查，再用一两个真实 PR 试验 AI 审阅是否能发现有用问题。AI 反馈由成员核对，同伴审阅和合并职责继续保留。

文档检查工作流在新建或更新 PR、PR 恢复打开或转为可审阅状态，以及推送 main 时运行，也支持合并后手动触发。固定检查不等于 AI 审阅或同伴确认，结果以当前提交的 Checks 为准。

## 已配置的文档与附件检查

在本机团队仓库根目录运行：

```bash
python3 scripts/check_docs.py .
python3 -m unittest discover -s tests -p 'test_check_docs.py' -v
```

检查器只用 Python 标准库，不联网、不读取密钥、不调用模型。它检查常见 Markdown 链接、图片、引用式链接，以及 Obsidian 双链；支持中文、编码空格、常见括号文件名和双链别名。无法唯一确定的同名双链需要补充目录。

代码块、行内代码、HTML 注释中的示例会跳过；Git 忽略的笔记不纳入文档扫描。它不检查外部网址是否在线、页内标题是否存在、原始 HTML 链接或动态生成路径，也不判断资料内容是否正确。指向本机绝对路径或仓库外部的链接会报错。

提交 PR 后查看“文档与附件检查”。失败日志会显示文件、行号、目标及原因；修复后推送原分支，检查会重新运行。单元测试包括“缺图失败、补图通过”的验收，防止检查器只会返回成功。

## 资源索引和 manifest 到底是什么

先分清“实际资料”和“介绍资料的目录”。下面只是假设示例，仓库中尚未新增这份课件。

假设以后放入一份 `课程资料/数据结构/第一章.pdf`：PDF 里是课件正文。

### 资源索引.md：给人看的目录笔记

它是一篇普通 Markdown 笔记，可以在 Obsidian 中打开和编辑。它介绍资料在哪里、有什么用、来自哪里，例如：

```text
资料：数据结构第一章课件
位置：课程资料/数据结构/第一章.pdf
用途：学习线性表前先复习基础概念
来源：填写实际来源
状态：待核对
```

在真实索引中可以把“位置”做成可点击链接。读者从索引跳到 PDF，省去逐层找文件。当前仓库的 [资源索引](资源索引.md) 已经是一篇这样的笔记，目前主要登记教材和项目入口。

### manifest.json：给程序读取的资料目录

它也记录资料信息，但用 JSON 的固定字段表示，方便脚本逐条读取。同一份示例资料可以写成下面这样；字段仅用于说明概念，具体系统有自己的格式：

```json
{
  "course": "数据结构",
  "path": "课程资料/数据结构/第一章.pdf",
  "source": "填写实际来源",
  "status": "待核对"
}
```

程序读取这条记录后，可以检查路径所指的文件是否存在，也可以据此生成网页目录。参考仓库还记录实际文件大小和哈希，用来发现文件变化或完全相同的重复文件。这些值应由脚本计算。

### 为什么我们暂时只用资源索引

| 文件 | 日常主要用途 | 团队当前情况 |
|---|---|---|
| 实际 PDF、代码、实验记录 | 保存要学习的内容 | 按实际进度逐步上传 |
| 资源索引.md | 让成员快速找到并了解资料 | 已有，继续维护 |
| manifest.json | 让程序批量检查资料、生成目录 | 暂未创建，资料多了再决定是否需要 |

两种目录都保存资料的说明，课件正文仍在 PDF 中。现在新增一份资料时，把文件放入合适目录，再在资源索引中补一行说明即可，不需要你额外手写 JSON。

## 同伴如何审阅

PR 中先看本次来源和验证说明，再在 Files changed 查看改动。至少核对一项关键内容，留下具体依据：例如一处算法、一条运行日志、一张附件，或一次课程提问的引用。

发现问题后由提交者在同一分支继续修改，PR 会更新。确认后再合并，其他成员拉取主分支。Discussions 用于讨论；正式成果保存在 Markdown 中，通过 Git 追踪。

## 方法来源

本 Skill 为三人私有团队重新编写，流程参考 [HENU-Final-Review](https://github.com/jry21223/HENU-Final-Review) 及其 [Agent工作说明](https://github.com/jry21223/HENU-Final-Review/blob/main/skills/henu-public-materials/SKILL.md)。参考仓库注明其公开资料整理与 PR 模板来源为 [final-review-template-kit](https://github.com/jry21223/final-review-template-kit)；本仓库没有复制其脚本或整套索引。

Codex 仓库技能路径和调用方式参照[官方 OpenAI 文档](https://learn.chatgpt.com/docs/build-skills)。
