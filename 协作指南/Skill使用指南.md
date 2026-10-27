# Skill使用指南

完整提示词与接入说明集中在这里；首页仅保留常用入口。

## 使用 Agent 整理资料并提交 PR

仓库已有[团队资料整理 Skill](../.agents/skills/team-learning-materials/SKILL.md)，可辅助分类、命名、维护链接和入口、检查改动并准备草稿 PR。操作说明见[Agent 资料整理指南](../协作指南/Agent资料整理指南.md)。

可以把以下提示词连同指定资料交给支持读取仓库文件的 Agent：

```text
请按本仓库 .agents/skills/team-learning-materials/SKILL.md 整理我指定的资料：
1. 读取协作约定、文件组织规范、目标目录说明和 PR 模板。
2. 查重，确认所属课程、实验或主题，保留真实来源与核对状态。
3. 整理文件名和附件，更新所属 README；新增入口时更新资源索引。
4. 运行布局与链接检查，核对本次差异，排除凭据及未授权共享的内容。
5. 在独立分支提交，创建或更新本任务的草稿 PR。
6. 说明检查结果和待同伴核对的内容，不自动合并。
```

Agent 整理、程序检查、本人理解和同伴审阅分别记录。实验区分本人真实运行、离线复核和教材参考；课程区分资料归档、成功入库、真实使用与同伴复测。

## 使用知识联动与周报 Skill

这两套 Skill 放在仓库的 `.agents/skills/`，供在本地打开仓库的 Agent 读取。它们分别负责知识积累与每日记录，提交团队资料时继续使用上面的团队资料整理 Skill。

| Skill | 什么时候用 | 主要产物 |
|---|---|---|
| [`lab-knowledge-loop`](../.agents/skills/lab-knowledge-loop/SKILL.md) | 核对学习进度；整理 DeepTutor 使用或实验；建立个人库并吸收团队知识 | 有来源的个人笔记、概念关联、选择共享的团队记录及 PR |
| [`lab-weekly-flow`](../.agents/skills/lab-weekly-flow/SKILL.md) | 收集本人微信与 Codex 学习素材；整理日记、周报草稿并按本人确认版本归档 | 原话收件、学习日记、待审核周报及版本确认记录 |

**个人库每人独立维护，团队远端共同使用。** 成员接受已有邀请后，将本团队仓库克隆到各自电脑；不必每人再创建一个团队远端。共享内容按任务选择，个人原话、配置、收件箱与草稿留在本人工作流目录，不全量传入团队库。Git 拉取也不会自动更新 DeepTutor 的课程索引。

### 让自己的 Agent 找到 Skill

克隆后，在自己的 Agent 中打开仓库根目录，让它先读 [AGENTS.md](../AGENTS.md)。支持项目 Skill 发现的 Agent 可从 `.agents/skills/` 读取技能；不同 Agent 的加载方式不同，不保证仅打开 GitHub 网页就能自动识别。未识别时，直接复制下面的文件路径提示词即可，无需复制其他成员的本机配置。

其他 Agent 没有 Codex 会话读取工具时，可以使用本人提供的对话摘录和 Hermes 素材；它应说明未自动覆盖的范围，仍可整理已有资料和周报。

已有个人库、准备整理一次真实学习时：

```text
请读取本仓库 AGENTS.md 和 .agents/skills/lab-knowledge-loop/SKILL.md。
我已有个人知识库，请先核对我提供的本机路径和原有规则，整理这次指定的
DeepTutor使用/实验记录，保留原问题、真实结果、来源和本人反馈，更新相关知识。
适合共享的内容单独列出；只在我指定的范围内准备团队贡献，不全量同步个人库，
不把AI解释当作我的心得，不自动合并PR。
```

没有个人库，或尚未使用 Hermes 时：

```text
请读取本仓库 AGENTS.md、.agents/skills/lab-knowledge-loop/SKILL.md
和 .agents/skills/lab-weekly-flow/SKILL.md，按新成员引导帮我接入。
先检查我的Obsidian个人库、Git、团队本地克隆和Hermes；已有的保留，缺路径时让我选择。
没有个人库时帮助建立最小空库；加入已有团队远端，不创建平行团队仓库。
按我实际使用的本地或云端Hermes引导微信接入，扫码和账号配置由我本人完成。
最后用一条真实文字记录核对收件箱，说明已经完成、尚未验证和下一步操作。
```

日常整理与周报：

```text
请读取 .agents/skills/lab-weekly-flow/SKILL.md，汇总我指定日期的学习相关
Codex可见对话和Hermes学习素材，区分成果、问题、计划、本人原话和AI摘要，合并重复事项。
更新个人学习日记，核对上期计划并更新本周待审核稿；未知信息标待补充。
展示真实来源、处理范围和稿件版本，等我确认具体版本后再归档，不代替我批准或发邮件。
```

### 接入方式与执行边界

- **本地 Hermes**：Hermes 与 Codex 共用成员选定的本机工作流目录，收件箱为该目录下的 `收件箱/`。
- **云端 Hermes**：先存 Linux 服务器收件箱，本机通过成员自己的 SSH 配置同步；不复制其他成员的服务器路径或凭据。
- **首次安装**：见[新成员首次接入](../.agents/skills/lab-weekly-flow/references/first-run.md)、[个人库与团队接入](../.agents/skills/lab-knowledge-loop/references/onboarding.md)和[Hermes 与微信部署](../.agents/skills/lab-weekly-flow/references/deployment.md)。检查/建库工具不等于安装 Hermes 本体，模型账号和微信扫码分别完成。
- **Windows**：按[Windows 指南](../.agents/skills/lab-weekly-flow/references/windows.md)使用自己的目录、Python 和 PowerShell；Windows 原生与 WSL 路径不要混用。
- **定时整理与审核**：需要在每位成员自己的 Codex 中设置时间、时区与运行环境；仓库不会自动安装别人的定时任务。语音和链接只按实际转写/读取范围整理；周报要由本人确认具体版本，网盘等外部归档仅在本人选定并接入后使用。

新成员以[首次实际验收](../.agents/skills/lab-weekly-flow/references/first-run.md#6-首次实际验收)为准：自己能打开个人库、接收一条真实记录、找到对应文件，并查看和确认一份草稿。代码测试通过不能代替实际微信收发、本人学习或同伴审阅。

