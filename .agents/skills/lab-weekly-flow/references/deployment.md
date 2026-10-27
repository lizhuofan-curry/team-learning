# 本地、云端与微信接入

## 先认识三种角色

Hermes是能够接收微信、使用模型与执行工具的Agent；微信网关是它的消息入口；Codex是本流程中整理本机材料、维护知识和编写周报的另一位助手。需要配置模型的是Hermes与Codex各自的现有环境，这个文件传输脚本不需要额外API Key。Obsidian只是编辑器，不负责运行Hermes。

| 方案 | 数据走向 | 适用情况 |
|---|---|---|
| 本地Hermes | 微信→本机Hermes→本机收件箱→Codex | 队友在自己电脑上运行Hermes；电脑和网关须在线 |
| 云端Hermes | 微信→服务器Hermes→服务器收件箱→SSH拉取→本机Codex | 云端持续接微信，本机上线后补同步；不能把云端路径当成本机路径 |
| 暂无Hermes | 手动写UTF-8素材文件→capture→Codex | 先使用记录与周报部分，接好微信再增加入口 |

## 队友从零接入微信

2026-10-27依据[Hermes官方安装说明](https://hermes-agent.nousresearch.com/docs/getting-started/installation)和[官方微信适配器说明](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/weixin.md)核对。命令或菜单随版本变化时先看`hermes --help`与`hermes gateway --help`，不要照抄旧菜单编号。

1. 从官方安装页选择自己系统的桌面包或CLI安装方式。Windows原生与WSL任选一种并保持路径一致；不要混用两套HOME。已安装者跳过。
2. 运行`hermes`或打开桌面端，用它的设置流程配置自己的模型。先完成普通对话，再接微信。不要把API Key写入团队Git。
3. 在Hermes实际运行的机器执行`hermes gateway setup`，选择Weixin/WeChat，按二维码向导用本人手机扫码及确认；已接好的用户跳过。二维码过期就用向导的新二维码。
4. 授权自己的私聊身份；按当前向导设置允许用户，避免无差别开放。扫码接入的是iLink机器人身份，不是接管全部个人微信，普通微信群消息不保证能收到。
5. 在另一个终端运行`hermes gateway run`（桌面已管理网关时不重复启动），发一条私聊并确认有回复。`hermes gateway status`用于检查状态；不能用“已扫码”代替实测。
6. 微信语音是否可转写要单独测试；语音不可用时先发文字。Hermes既有STT、模型、网络问题按真实日志处理，不由本技能扫描凭据。

首个普通消息能往返后，再安装下面的学习采集技能。无需为本流程加入微信群或读取整个聊天历史。

## 安装采集技能：本地模式

Windows用户先读[Windows适配与验收](windows.md)，使用PowerShell例子和配置生成器；不要照抄Mac路径。

先确定真正的Hermes数据目录。macOS/Linux经常为`~/.hermes`；Windows须查看自己安装的实际数据路径，可能在`%LOCALAPPDATA%\hermes`，不硬编码另一位成员的目录。自定义profile的Hermes使用该profile的home。

在**本机**执行（将尖括号占位替换为自己的路径，命令中的脚本位于当前Skill文件夹内）：

```text
python scripts/install_hermes.py --hermes-home <Hermes数据目录> --workflow-root <个人学习工作流目录>
```

安装器新建独立`lab-learning-capture`用户技能、专用运行脚本和位置配置，不修改微信账号或模型设置。已存在且内容不同的文件不会直接覆盖。确保Codex的`--root`与这里的`--workflow-root`相同。重开一次Hermes对话并要求读取`lab-learning-capture`技能，以便发现新技能；不需要因此重装Hermes或微信。

本机`config.local.json`可用：

```json
{
  "mode": "local",
  "personal_vault": "替换为自己的Obsidian根目录",
  "raw_captures": "仅在本人选择原话归档后填写自己的raw/学习记录/微信素材",
  "team_repo": "替换为团队库的本地克隆",
  "deeptutor_root": "替换为DeepTutor项目目录",
  "weekly_archive": "替换为自己的正式周报目录",
  "obsidian_reports": "替换为自己的Obsidian输出目录/周报"
}
```

已有配置不整份替换，补需要的字段。尚未决定的归档路径先不填。收件箱、配置、草稿和批准记录放本人目录，不作为团队共享内容。

## 安装采集技能：云端模式

先用本人已配置的SSH Host连接服务器。把本技能内`scripts`、`assets/hermes-skill`复制到服务器一个临时目录，在服务器执行上面的安装命令；`--hermes-home`与`--workflow-root`填写**服务器**目录。推荐服务器工作流目录放在Hermes数据目录的`lab-learning`，不要使用Mac路径。

本机配置改为：

```json
{
  "mode": "cloud",
  "remote": {
    "host": "自己的SSH-Host别名",
    "python": "python3",
    "root": "/服务器绝对路径/.hermes/lab-learning",
    "script": "/服务器绝对路径/.hermes/lab-learning/learning_flow.py"
  }
}
```

保留本机归档相关字段。`sync`只拉取专用收件箱和批准记录，`review`只送入本人周报待审核目录；不触碰微信账号文件、不读取服务器其他历史聊天。

云端只需要`lab-learning-capture`技能和脚本，不安装Codex。Mac/Windows端安装`lab-weekly-flow`，由Codex整理。首次测试用`kind=test`，不能把传输演示当作本人真实微信学习记录。
