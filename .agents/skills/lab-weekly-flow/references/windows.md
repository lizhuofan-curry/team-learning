# Windows适配与验收

脚本使用Python 3.9及以上的标准库，Mac、Windows、Linux共用代码。Windows运行方式与Linux服务器不同，不复制别人的绝对路径。中文、空格、Emoji、UTF-8 BOM配置、CRLF稿件字节及安装/归档流程纳入跨平台CI；微信GUI、语音模型和实际SSH账号仍需在成员机器验证。

## Windows本地Hermes

没有个人知识库时先使用[首次接入](first-run.md)中的onboard_member.py，建立本人选定的空库；已有库不会自动重构。

1. 安装可用Python：PowerShell执行`py -3 --version`；若`py`不可用且`python --version`正常，可换成`python`。避免使用会打开商店的空命令别名。
2. 从Hermes当前设置确认真实数据目录。原生Windows数据路径与WSL的`~/.hermes`不同，不能把Mac或腾讯云的home直接搬过去。
3. 解压技能包，以下示例将它放在`E:\学习技能包`，工作流放`E:\学习工作流`。PowerShell命令使用双引号包含空格/中文路径：

```powershell
$skillDir = "E:\学习技能包\lab-weekly-flow"
$hermesHome = "实际Hermes数据目录"
py -3 "$skillDir\scripts\install_hermes.py" --hermes-home "$hermesHome" --workflow-root "E:\学习工作流"
py -3 "$skillDir\scripts\configure.py" --root "E:\学习工作流" --mode local --personal-vault "E:\知识库\我的Wiki" --weekly-archive "E:\周报" --archive-wechat-originals
```

`--archive-wechat-originals`仅在本人选择追加归档微信原话时使用；其他raw保持只读。配置生成器自动转义Windows反斜杠，保留原有自定义字段，配置变化前保存一份备份；不必手写含反斜杠的JSON。实例目录按自己电脑替换，原生Windows无需安装bash来跑这些Python脚本。

已有周报目录会保留。自己的库没有raw/wiki结构时，先选实际归档位置，再用`--obsidian-reports "E:\自己的库\周报"`填写；不要照搬另一位成员的目录结构。

让Hermes读取新采集技能，向微信机器人发一条文字，核对素材编号，再让Codex整理。单独测试中文语音后才能说语音可用；腾讯云上已装的silk/whisper脚本不会自动出现在Windows。

## Windows连接Linux云端Hermes

本机是Windows，Hermes运行在Linux服务器时，仍使用cloud模式。先确认PowerShell的`ssh 自己的Host别名`能连接；OpenSSH Client不存在时通过Windows“可选功能”或已使用的WSL环境配置，不在脚本中静默安装系统组件。

```powershell
py -3 "$skillDir\scripts\configure.py" --root "E:\学习工作流" --mode cloud --remote-host "自己的Host别名" --remote-root "/home/自己的用户/.hermes/lab-learning"
py -3 "$skillDir\scripts\learning_flow.py" --root "E:\学习工作流" sync
```

云端路径必须是Linux服务器路径；Windows本地配置仍使用E盘路径。此版cloud传输针对Linux SSH服务器，不声称支持Windows作为SSH服务端的PowerShell命令解释。

## 编码与换行

- 协议和配置统一UTF-8；脚本显式配置标准输入输出。PowerShell 5.1常见的UTF-8 BOM配置可读取。
- 长原话建议另存UTF-8文本文件后用`--text-file "E:\路径\原话.txt"`，避免PowerShell 5.1的文本管道在到达Python之前已损坏字符。文件方式优先于管道，PowerShell 7和5.1的默认编码并不相同。
- 批准按原始字节SHA-256绑定。编辑器把CRLF改成LF也会产生新版本，要重新送审；归档保留获批字节，不顺便转换换行。
- Windows休眠或Codex关闭时，本机定时整理不能保证执行；云端可继续收件，上线后补同步。

## 本机验收命令

```powershell
py -3 "$skillDir\scripts\test_learning_flow.py"
py -3 "$skillDir\scripts\test_portable_cli.py"
```

CI通过只证明脚本在对应Windows/Python版本的功能，不能代替微信扫码收发、真实语音和队友账户/Obsidian现场验收。
