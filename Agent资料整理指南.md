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

老师禁止大模型参与的读后感及相关工作不使用本技能处理。普通周报只按本人授权归档已确认原文，不代写其他成员经历。

## Actions 是什么

GitHub Actions 是自动运行任务的平台。运行什么取决于仓库的工作流文件。

参考仓库的[资料校验流程](https://github.com/jry21223/HENU-Final-Review/blob/main/.github/workflows/validate-materials.yml)执行 Node/Python 脚本，检查文件、索引和规则；这部分没有调用大模型。AI 审阅需要另行接入模型或审阅服务。自动检查通过，也不能保证知识内容正确。

本次只新增团队 Skill 和完善 PR 模板，没有配置本仓库的 Actions 或 AI 自动审阅。

## manifest 是什么

manifest 在这里是“资料登记册”，通常保存为 `manifest.json`，相当于程序能读取的资源索引。每条记录可以写：课程、资料类型、文件路径、来源、大小，以及用于识别文件是否变化的哈希。

例如，人看的索引可以是一行：

| 课程 | 文件 | 来源 | 核对状态 |
|---|---|---|---|
| 数据结构 | 一份实际课件的仓库路径 | 实际来源 | 待核对或已核对，并附依据 |

JSON 只是把同类信息改成程序方便读取的格式。它本身不存放课件正文，也不判断答案是否正确。团队现在继续维护 [资源索引](资源索引.md) 即可，暂未引入 manifest。

## 同伴如何审阅

PR 中先看本次来源和验证说明，再在 Files changed 查看改动。至少核对一项关键内容，留下具体依据：例如一处算法、一条运行日志、一张附件，或一次课程提问的引用。

发现问题后由提交者在同一分支继续修改，PR 会更新。确认后再合并，其他成员拉取主分支。Discussions 用于讨论；正式成果保存在 Markdown 中，通过 Git 追踪。

## 方法来源

本 Skill 为三人私有团队重新编写，流程参考 [HENU-Final-Review](https://github.com/jry21223/HENU-Final-Review) 及其 [Agent工作说明](https://github.com/jry21223/HENU-Final-Review/blob/main/skills/henu-public-materials/SKILL.md)。参考仓库注明其公开资料整理与 PR 模板来源为 [final-review-template-kit](https://github.com/jry21223/final-review-template-kit)；本仓库没有复制其脚本或整套索引。

Codex 仓库技能路径和调用方式参照[官方 OpenAI 文档](https://learn.chatgpt.com/docs/build-skills)。
