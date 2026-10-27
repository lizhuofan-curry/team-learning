# Windows与学习工作流

新增两套可复用技能，将个人Obsidian、DeepTutor、团队Git和本人审核的周报串联。每位成员使用自己的路径与微信账号，不共享运行配置、收件箱或凭据。

- [知识联动技能](../.agents/skills/lab-knowledge-loop/SKILL.md)：核对学习证据、课程使用、团队共享和个人吸收。
- [素材与周报技能](../.agents/skills/lab-weekly-flow/SKILL.md)：本地/云端Hermes采集、Codex对话汇总、周报版本审核。
- [Windows安装与验收](../.agents/skills/lab-weekly-flow/references/windows.md)：PowerShell、中文路径、配置生成器和运行测试。
- [Hermes与微信接入](../.agents/skills/lab-weekly-flow/references/deployment.md)：未使用Hermes的成员从普通对话、微信扫码和私聊测试开始。

Python脚本只做存储、校验与传输，学习提炼由Agent依照来源和证据执行。语音、视频、文章需要按实际得到的音频、字幕和正文核对；仅收到链接不算学完。

GitHub Actions在Windows/Python 3.9、Windows/Python 3.12和Linux/Python 3.12运行核心与CLI集成测试。CI通过代表脚本验证，微信现场收发、语音转写、实际SSH和同伴使用仍需成员真实完成。

每人先用自己的文字完成一次收件和归档，再尝试一份有明确周次的待审核稿。模型不能代替本人批准；新稿送审后旧稿批准不再用于归档，不自动提交老师或合并团队PR。

## 新成员从哪里开始

- [个人知识库与团队加入](../.agents/skills/lab-knowledge-loop/references/onboarding.md)：没有个人库时引导建立，有团队远端时只克隆，不另建平行远端。
- [首次接入与检查工具](../.agents/skills/lab-weekly-flow/references/first-run.md)：onboard_member.py可建立本人选定的空库和本机位置配置，保留既有笔记；Hermes安装、账号设置和微信扫码分别引导。
- [语音排查](../.agents/skills/lab-weekly-flow/references/speech.md)：先确认实际转写命令、语言和模型，再用真实语音验证。云端API需本人选择服务，不向聊天索取Key。

安装与克隆不等于实际学习完成；个人知识与团队贡献按本人选择分别更新。新成员工具不会安装Hermes本体、替本人扫码或自动创建远端仓库。
