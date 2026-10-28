# 三人团队学习知识库

共享 Agent Book 实验、专业课程资料、DeepTutor 使用记录和学习笔记：**学习 → 留证据 → 提交 PR → 同伴核对 → 吸收进个人知识库。**

## 找资料

| 目录 | 内容 |
|---|---|
| [课程资料](课程资料/README.md) | 各课程的课件、资料来源、DeepTutor导入与真实使用 |
| [实验资料](实验资料/README.md) | Agent Book 实验代码、运行条件、结果与分析 |
| [共同知识](共同知识/README.md) | 概念笔记、DeepTutor 源码分析和核对后的讨论结论 |
| [周报](周报/README.md) | 按成员、周次保存的本人确认原文与附件 |

[成员与课程分工](分工与课程覆盖.md) · [资源索引](资源索引.md) · [协作指南与模板](协作指南/README.md) · [讨论区](https://github.com/lizhuofan-curry/team-learning/discussions)

## 让 Agent 帮忙

在 Agent 中打开本仓库根目录，让它先读 [AGENTS.md](AGENTS.md)，再按任务选择 Skill：

| Skill | 用途 |
|---|---|
| [lab-knowledge-loop](.agents/skills/lab-knowledge-loop/SKILL.md) | 整理课程、阅读、实验与项目知识，联动个人Obsidian库与团队协作，按需使用DeepTutor |
| [lab-weekly-flow](.agents/skills/lab-weekly-flow/SKILL.md) | 接入本地或云端 Hermes/微信，整理学习日记与周报，按本人确认的版本归档 |
| [team-learning-materials](.agents/skills/team-learning-materials/SKILL.md) | 分类、命名、维护索引和链接，检查改动并准备团队 PR |

```text
请先读本仓库 AGENTS.md，按我的任务选择对应 Skill。
先检查已有环境和资料，再引导我完成；保留本人原话，说明真实结果与待办。
```

[团队完整教程](协作指南/团队知识库完整使用手册.md) · [DeepTutor教程](协作指南/DeepTutor完整使用手册.md)

[完整用法与可复制提示词](协作指南/Skill使用指南.md) · [新成员首次接入](.agents/skills/lab-weekly-flow/references/first-run.md) · [Windows 指南](协作指南/Windows与学习工作流.md)

每人维护自己的个人库和工作流，团队共用这个远端仓库。个人收件箱、草稿、密钥与本机配置不上传；Skill 不会自动装好 Hermes、账号或定时任务，Git 更新也不会自动更新 DeepTutor 索引。

## 参与共建

1. 克隆仓库，按[Git 协作入门](协作指南/Git协作入门.md)新建分支；Obsidian 可直接打开本地克隆目录。
2. 按[文件组织规范](协作指南/文件组织规范.md)放资料，更新所属目录的 README，写明来源、实际结果和待核对内容。
3. 检查后提交 PR，由另一成员留下具体意见再合并；按[协作约定](协作指南/协作约定.md)共享、互审和吸收更新。

在仓库根目录检查（Windows 可用 `python` 或 `py -3`）：

```bash
python3 scripts/check_layout.py .
python3 scripts/check_docs.py .
```

[Actions](https://github.com/lizhuofan-curry/team-learning/actions)自动检查文件结构、链接与附件；知识正确性和实际学习效果仍需本人及同伴核对。
