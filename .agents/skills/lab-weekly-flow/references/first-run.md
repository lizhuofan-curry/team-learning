# 给新成员的首次接入流程

这是 Agent 引导完成的接入流程，配套脚本只能检查和创建本人选择的本地结构；不能替本人注册模型账号、接受GitHub邀请或微信扫码。先检测已有组件，已经配置的跳过，不重复安装。完整接入时，先按[接入进度与续办](onboarding-state.md)读取或建立私人进度，再依本页逐项执行。

## 0. 从仓库克隆或技能包找到脚本

| 已有内容 | lab-weekly-flow 的实际位置 |
|---|---|
| 已克隆团队仓库 | 团队根目录下 `.agents/skills/lab-weekly-flow` |
| 已解压技能包 | 解压后含本技能 `SKILL.md` 和 `scripts` 的 `lab-weekly-flow` 目录；先检查实际层级 |
| 只有网页读取能力 | 先读取说明；不能执行下列命令时给成员一条当前可做的操作并核对反馈，不报告脚本已运行 |

下面变量是示例位置，Agent 先替换为成员实际选定路径。Windows 没有 E 盘就使用本人选择的其他数据位置；不把示例直接写入配置。

Windows / PowerShell（已克隆时）：

```powershell
$teamDir = "E:\团队知识库"
$skillDir = Join-Path $teamDir ".agents\skills\lab-weekly-flow"
$workflowDir = "E:\学习工作流"
$vaultDir = "E:\知识库\我的Wiki"
Test-Path "$skillDir\scripts\onboard_member.py"
py -3 --version
py -3 "$skillDir\scripts\onboard_member.py" --help
```

macOS/Linux / shell（已克隆时）：

```sh
team_dir="$HOME/团队知识库"
skill_dir="$team_dir/.agents/skills/lab-weekly-flow"
workflow_dir="$HOME/学习工作流"
vault_dir="$HOME/知识库/我的Wiki"
test -f "$skill_dir/scripts/onboard_member.py"
python3 --version
python3 "$skill_dir/scripts/onboard_member.py" --help
```

解压方式只需把 `skillDir` / `skill_dir` 换为实际技能目录，其余变量仍对应成员自己的三个独立目录。检查脚本不存在时先纠正路径，不在团队根目录运行不存在的 `scripts/onboard_member.py`。`py -3` 不可用时只在确认 `python --version` 正常后换成 `python`。

本工作流脚本要求 Python 3.9+；这是它们的兼容范围，不是 Hermes 本体的运行时要求。Hermes 使用当前官方安装方式及配套运行时，不用任意系统 Python 强行替换。查看 `--help` 不会创建个人库或完成账号配置。

## 1. 明确四个位置

- 个人Obsidian库：保存本人资料和理解，一人一份。
- 团队库本地克隆：共同远端在各自电脑的一份副本，不另建每人一个团队远端。
- 个人学习工作流：收件箱、草稿、确认记录和本机配置，不放进团队Git。
- Hermes数据目录及运行位置：本地机器或Linux云端，不能把客户端电脑当成运行机器。

缺路径时让成员选择；Windows示例使用E盘，不强行使用不存在的磁盘。

## 2. 检查或建立最小个人库

沿用第 0 节已核实的变量。只有本人选择建立空库时使用 `--initialize-personal-vault`，不需要新建时去掉该参数。

```powershell
py -3 "$skillDir\scripts\onboard_member.py" --root "$workflowDir" --personal-vault "$vaultDir" --team-repo "$teamDir" --team-url "https://github.com/lizhuofan-curry/team-learning" --initialize-personal-vault
```

```sh
python3 "$skill_dir/scripts/onboard_member.py" --root "$workflow_dir" --personal-vault "$vault_dir" --team-repo "$team_dir" --team-url "https://github.com/lizhuofan-curry/team-learning" --initialize-personal-vault
```

已有raw/wiki库会保留。非空未知目录不会被重构，先交给 Agent 检查原有组织方式。脚本不创建个人Git远端、不克隆团队Git，只给出成员确认后的克隆命令；不伪造第一份学习心得。

输出`接入检查.json`包含本机目录、Git/Hermes/SSH可执行文件是否发现，以及后续待办。可执行文件未在PATH上不等于软件未安装，桌面包需另检查；不要看到false就直接重装。脚本没有检查模型可用或微信已连通，不能把报告当作全部成功。

在Obsidian中打开自己的个人库目录。本人提供一份真实材料后，再按知识联动Skill生成来源和知识关联。个人 Git 首次私有同步、Obsidian 连接及可选插件步骤见另一个 lab-knowledge-loop 技能的 `references/onboarding.md`；从团队克隆读取时路径为 `.agents/skills/lab-knowledge-loop/references/onboarding.md`，独立安装时从当前可用技能定位，不猜跨目录地址。

## 3. 团队仓库加入

使用本人GitHub账号接受已有邀请，确认仓库地址，然后克隆到单独目录。已有本地克隆就核对它，不新建平行仓库或自动覆盖未提交文件。成员姓名、账号、课程认领由本人填写；第一次PR由另一位成员实际审阅。

## 4. Hermes安装与微信

遵循[部署与微信接入](deployment.md)的官方来源。先检测是否安装；无Hermes才选择官方桌面包或CLI安装途径。模型认证由成员在自己的设置入口配置，不向聊天索要Key、不保存进团队文件。普通对话成功后，在Hermes实际运行的那台机器运行微信向导，由本人扫码确认。

本地Hermes无需服务器和SSH；云端模式需本人已可访问的Linux服务器。本文不把“引导安装”称为“无人值守一键部署”。

## 5. 安装学习采集并确认收件位置

Hermes已可普通私聊后，在 Hermes 实际运行的机器安装采集功能。本地模式可以沿用上述变量；先把示例数据目录替换为本人当前 profile 的真实位置：

```powershell
$hermesHome = "本机Hermes实际数据目录"
py -3 "$skillDir\scripts\install_hermes.py" --hermes-home "$hermesHome" --workflow-root "$workflowDir"
py -3 "$skillDir\scripts\configure.py" --root "$workflowDir" --mode local --personal-vault "$vaultDir"
```

```sh
hermes_home="本人当前profile的实际数据目录"
python3 "$skill_dir/scripts/install_hermes.py" --hermes-home "$hermes_home" --workflow-root "$workflow_dir"
python3 "$skill_dir/scripts/configure.py" --root "$workflow_dir" --mode local --personal-vault "$vault_dir"
```

云端运行 Hermes 时不要在客户端套用这两段本地安装；先按[云端部署](deployment.md#安装采集技能云端模式)把安装资源准备到服务器，使用服务器路径安装，并给客户端设置 cloud 配置。安装器会给Hermes生成`capture.local.json`，其中`workflow_root`决定专用收件箱位置。

例如本地工作流为`E:\学习工作流`，收件箱就在`E:\学习工作流\收件箱\日期\编号.json`。本地模式Codex和Hermes共用该目录，无需跨机器同步；归档到Obsidian的raw目录由本人另行选择，不等于机器可读收件箱。

使用`configure.py --help`核对当前可用选项，再填本人选定的正式周报目录与 Obsidian 周报输出目录；尚未选择则记待配置，不擅自沿用示例。只有本人希望追加原话时才使用`--archive-wechat-originals`。原话、AI摘要、测试、计划与成果分开。

已有个人库的`obsidian_reports`会保留，不因再次指定库路径就换成默认目录。普通平铺Obsidian库未选归档目录时，工具会提示待配置；让本人选定后用`--obsidian-reports`明确填写，不擅自给旧库增加wiki层级。

## 6. 选择需要的自动化模块

先检查已有配置及任务，说明各项用途，只对尚未决定的项目收集本人选择。完整接入不意味着所有可选模块必须开启；基础文字采集与手动整理可先使用。频率、运行机器、时区及外部语音服务选择分别记录，不照搬另一位成员的设置。

| 模块 | 何时需要与读取入口 | 实际验收依据 |
|---|---|---|
| 按要求记录学习文字 | 已安装的采集技能及[日常运行](operations.md) | 本人真实输入得到素材编号，实际收件正文与原话对应 |
| 自然学习对话自动保存 | 本人希望不必每次说“记录学习”时读[自动采集](automatic-capture.md) | 当前网关真实 hook 生效；本人自然提问对应的状态与素材可核对；测试与无关内容排除 |
| 云端到本机的素材同步 | Hermes 在云端时读[部署](deployment.md)与[日常运行](operations.md)；同机共用 ROOT 无需 SSH | 两侧同编号和内容哈希一致，重复同步不重复写入，断网保留待同步；同机核对双方读取同一 ROOT |
| 两个 Agent 的状态与意见交换 | 本人选择双向协作时读[协作协议](collaboration.md) | 消息送达、实际读取回执、处理结果分别记录；复制文件不等于模型已读 |
| 定时整理日记与周报草稿 | 本人选择周期后读[对话与多媒体](conversations-and-media.md)及[日常运行](operations.md#默认执行方式和停止点) | 核对任务位置、时区、下一次运行；至少一次实际执行保存覆盖范围和输出；未运行保持待验证 |
| 学习链接自动补读 | 本人选择时读[媒体队列](media-queue.md)与[路由](media-routing.md) | 本人一条真实链接按实际可读范围回传，定时运行另验；无字幕长音频的处理先按本人策略决定 |

安装器不会启用自然对话 hook、配置双向协作或创建模型整理任务。文件传输调度只搬文件，不启动模型；本机睡眠/离线时不保证执行，恢复后核对未覆盖日期。首次人工执行成功不能冒充无人值守定时已通过。停用与恢复使用各模块文档的入口，保留素材和批准记录。

## 7. 首次实际验收与交接

1. 本人从微信发一条真实文字学习记录，得到素材编号。
2. Codex核对收件文件，再存原话、来源与日记。电脑或云端是哪一侧保存要说清楚。
3. 本人再发一条短语音并核对转写。识别差时按[语音排查](speech.md)处理，不能让模型自动润色成“正确原话”。
4. 用实际素材生成一份带周次的草稿并展示，记录来源与未完成项。接入完成不要求本人立即批准真实周报；本人决定送审或归档时才按精确版本确认。审核演练使用隔离测试稿，不能伪造真实批准。
5. 对本人选用的模块逐项写入[接入状态](onboarding-state.md)。首轮定时任务成功后保留覆盖范围与输出证据，才称自动流程已实测。Windows执行本包两组测试，微信账号、语音、Obsidian及实际定时运行仍须现场验收。

遇到缺模型账号、未接受邀请或二维码确认时，清楚说明需要成员做哪一步，并继续完成不依赖该步骤的本地准备；不要代填账号或称已完成。
