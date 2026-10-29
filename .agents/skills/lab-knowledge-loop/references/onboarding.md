# 新成员接入：个人库与共同团队库

用户要求接入团队、建立第二大脑或检查发现尚无个人库时，使用本引导。先区分“个人知识库”“团队仓库远端”和“团队仓库本地克隆”，不能把三者混成一个目录。

## 先确认成员现状

读取本次提供或已授权配置中的路径，检查Obsidian、Git及登录状态、个人库是否存在、团队邀请是否已接受。没有证据时标待确认，不照抄别人的姓名、邮箱、路径或账号。仅检查相关状态，不读取Token或私人聊天。

已有个人库就保留其结构和规则；已有团队远端就加入该远端，不新建同名/平行团队库，不fork取代同队协作，除非用户明确选择这种模式。

## 没有个人库时

1. 在成员选择的本人电脑目录建立独立个人库，例如Windows的`E:\知识库\我的Wiki`。缺位置时先询问；不要在系统盘或团队克隆目录中随意放置。
2. 建立最小结构：`raw`保存本人原始资料，`wiki/sources`保存来源，`wiki/concepts`保存可复用理解，`wiki/outputs`保存日记和已确认输出，`wiki/templates`保存实际需要的模板。不要创建空泛的大量主题目录。
3. 新建首页和一条真实学习记录，连接原始材料、本人困惑及一个概念。未知作者/日期/掌握程度不编造。说明原话和AI解释如何分开。
4. 按下方[Obsidian 打开与可选 Git 插件](#obsidian-打开与可选-git-插件)打开此目录，验证能找到首页及原始记录。仅创建目录不能称成员已使用Obsidian。
5. 按[个人 Git 与首次私有同步](#个人-git-与首次私有同步)选择保存方式。已有仓库沿用；需要私有远端时，在成员自己的账号按授权创建和连接。不要自动公开、复制其他人的个人库或沿用他人Git身份。
6. 将实际路径写入成员本机`config.local.json`；个人设置与凭据不进团队共享库。原话追加至raw须本人选择专用目录，已有raw保持只读。

不要求新人先安装当前用户个人库的全部定制检查脚本；有现成规则就遵守，新库先验证来源和链接即可。个人库搭好后再逐步增加所需知识，不把自动模板当成真实学习产物。

## 个人 Git 与首次私有同步

这部分处理个人库备份；团队资料仍按团队分支和 PR 协作。成员选择暂时只存本机时，保留“未启用远端”，不要报告 GitHub 同步已完成。

### 先选与现状对应的分支

| 现状 | Agent 下一步 | 不能据此声称什么 |
|---|---|---|
| 只有本地笔记，还没有 Git | 核对目录不在另一个仓库内部，再初始化本目录；已有笔记保留 | 初始化成功不代表远端已建立 |
| 本地已经是 Git 仓库 | 查看真实根目录、分支、修改和远端；沿用本人身份与历史 | 不因为缺少远端就重新建库或覆盖 `.git` |
| GitHub 已有个人库，本机尚未克隆 | 核对本人账号、仓库可见性及内容，再克隆到选定空目录，用 Obsidian 打开该目录 | 不在已有笔记上直接克隆；旧笔记需比较后按选定范围迁入 |
| 本机与远端都有内容，或已经存在不同 origin | 先 fetch 并比较历史及实际文件，说明差异后继续；保留两侧内容 | 不自动替换 origin、强推或用远端覆盖未提交笔记 |

在本人选定的个人库目录检查：

```sh
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
git remote -v
git config user.name
git config user.email
```

尚未初始化时前几项报“不是 Git 仓库”是现状，不是初始化失败。若返回的是上级仓库根目录，先解决目录位置，不在其中再建嵌套个人库。远端地址只记录无凭据形式；身份缺失时请成员提供自己选择的名字与邮箱，仅在本库配置，不沿用团队所有者的值。

### 第一次上传先核对文件范围

1. 让成员选择需要备份的笔记、附件及 Obsidian 设置。私人远端也不用于保存 API Key、账号令牌或完整运行环境；工作流收件箱和本机配置继续留在独立工作流目录。
2. 合并已有 `.gitignore`，不覆盖本人规则。下面只是常见排除项，按本库实际文件选择；`raw` 是否备份由本人决定，不整目录默认排除，也不整库默认上传。

```gitignore
.env
.env.*
!.env.example
*.pem
*.key
config.local*.json
.venv/
node_modules/
.DS_Store
.obsidian/workspace*.json
.obsidian/cache/
.obsidian/plugins/**/data.json
```

3. GitHub Desktop 在 Changes 中逐个选择文件；CLI 用 `git add` 指定实际文件或已确认目录，再看 `git diff --cached --name-status` 和 `git diff --cached`。不要先暂存全部，再把未知文件当作已经同意上传。
4. `.gitignore` 不会移除已经跟踪的文件；用 `git ls-files` 核对当前跟踪范围。发现不该共享的已跟踪内容先保留现场、确认移除方式；涉及已外泄凭据时由本人作废更换，删除当前文件不等于清掉历史。

### GitHub Desktop 路线

1. 在 Desktop 登录成员自己的账号。已有本地 Git 用 `File → Add Local Repository` 选个人库；没有 Git 时可按下方 CLI 在本目录初始化后添加，避免误在笔记目录内再建一个同名子目录。
2. 在 Changes 核对刚才选定范围，填写本次真实提交说明并 Commit。初始化或提交均只发生在本机。
3. 新远端使用 `Publish repository`，核对发布账号为本人、名称为本人选择，并保持 `Keep this code private`；出现 Organization 选项时，个人账号选 `None`。界面与本版不同就查看当前菜单；不要为继续流程选成公开。
4. 已有远端时先 Fetch；只有确认能安全更新时 Pull，再 Push。认证在 Desktop/浏览器的本人登录界面完成，不向聊天粘贴令牌。
5. 在 GitHub 打开对应仓库，核对 private 标记、当前分支、最新提交和一份本次笔记。记录提交号，不能把按钮点击成功当作远端已核对。

### CLI 路线

以下从成员个人库根目录运行；`git init -b main` 仅适用于尚无 Git 的新库，已有库跳过初始化并保留实际分支。较旧 Git 不支持 `-b` 时先查看本机帮助，不擅自更名已有分支。

```sh
git init -b main
```

按前文核对身份、排除项并暂存选定文件后再提交：

```sh
git diff --cached --name-status
git diff --cached
git commit -m "建立个人知识库的首次选定备份"
```

在 GitHub 本人账号的 New repository 页面创建 **Private** 仓库。此分支用于上传已有本地历史，新建远端时不要另勾 README、许可证或 `.gitignore` 生成第二份初始历史；已有内容的远端则回到上方“本机与远端都有内容”分支。创建和上传均按当前及已有授权执行。

仅当当前没有 origin 时，将成员自己的无凭据地址连接为 origin。下面命令从实际已选 origin 推送**当前**分支，不把示例账号、仓库名或另一人的身份写进命令：

```text
git remote add origin 本人新建私有仓库的HTTPS地址
git push -u origin HEAD
```

最后核对：

```sh
git rev-parse HEAD
git branch -vv
git ls-remote origin HEAD
git status --short --branch
```

新远端默认分支通常指向首次推送分支，此时 `ls-remote origin HEAD` 可与本机提交比较；已有远端默认分支与当前分支不同，就核对 `refs/heads/当前实际分支`，不要误判 HEAD 不同为上传失败。另在 GitHub 页面核对 private 可见性。显示上游且 ahead/behind 为 0，只证明当前 Git 版本一致，不证明未跟踪文件、忽略文件或本人所有笔记都已备份。

### Obsidian 打开与可选 Git 插件

1. 检查已有 Obsidian；缺失时按本人系统使用[官方下载](https://obsidian.md/download)。在 Vault 切换器选择“打开文件夹作为仓库”，打开本人实际个人库目录；已接入 Git 时与个人 Git 根目录一致。已有库直接复用，不另造一份拷贝。
2. 打开首页和本人一份真实笔记；在 Obsidian 保存一次本人选定的实际修改，再检查该目录的 Git Changes，确认看到的是同一个文件。没有真实修改时核对路径和文件内容即可，编辑联动仍待实测。
3. 使用 GitHub Desktop/终端同步已经能完成备份；插件是成员可选项。需要在 Obsidian 内操作时，进入 Settings → Community plugins，按本人选择启用社区插件，Browse 搜索 **Git**，核对插件 ID 为 `obsidian-git`、作者为 **Vinzent**，Install 后 Enable。已有插件直接检查其版本与设置。
4. 桌面插件使用本机 Git；系统终端 Git 可用而插件找不到时，核对插件的 Git 路径设置和 Obsidian 启动环境。插件不会替本人创建 GitHub 授权；使用已配置的 HTTPS 凭据管理或 SSH，不把 Token 存进笔记。
5. 初次保持自动同步未开启，用命令面板的 Git `Open source control view` 查看暂存和差异。明确提交选择后执行 `Commit with specific message`，再分别 Pull/Push；当前命令和设置以已安装版本为准。`Commit-and-sync` 可能自动暂存更多文件，启用前核对 `Stage all changes when nothing is staged` 等行为，不能假设只上传当前笔记。
6. 远端领先或有冲突时先保留本机修改，结合差异处理；不要选“丢弃全部改动”或删除 `.git`。本人确认手动同步正常后，才选择自动提交/推送/启动拉取的项目和周期，记录一次实际运行。关闭自动任务后手动同步仍可使用；团队库不照搬个人库的自动推送设置。

Git 页面与 Obsidian 都能看到同一份笔记、一次实际同步在远端可见，才分别记“Vault 连接已验证”和“个人同步已验证”。未选择插件可记“插件暂不启用”，不阻断手动方案。

操作来源：[GitHub Desktop 添加现有库](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop)、[Desktop 发布已有项目](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop)、[Obsidian 社区插件](https://help.obsidian.md/Extending+Obsidian/Community+plugins)、[Git 插件维护者说明](https://github.com/Vinzent03/obsidian-git)。菜单和命令可能随版本变化，记录本轮实际版本及可观察结果。

## 已邀请到现有团队库时

1. 使用成员自己的GitHub账号接受邀请，核对目标确为大家共同维护的同一个远端仓库。
2. 克隆到本人电脑单独目录，例如`E:\团队知识库`。这是一份共同仓库的本地副本，不是另一个团队远端，不放进个人库的raw。
3. 读取团队README和协作规则，使用自己的Git身份提交；不覆盖已有本地目录或强制拉取覆盖未提交修改。
4. 成员实际填写姓名、账号、所负责课程与当前进度，不由AI替团队分工。
5. 以一份本人同意共享的真实资料建立分支，运行项目检查并提交PR；由另一位成员留具体意见。邀请、克隆、能提交、能拉取他人合并内容分别确认。

共享库可在Obsidian中作为另一个仓库打开；个人库和团队库可切换使用，但不要求把全部个人笔记同步到团队。任务只涉及个人整理时不改团队文件；涉及共享时只提交明确选择的内容。团队知识进入个人库时保留文件路径和提交版本，再补本人的理解与使用结果。

## 新成员验收

交付两个本地路径、共同远端地址、真实资料例子、待确认项，以及下一步该由成员完成的动作。安装、首次使用、个人知识吸收、团队贡献和同伴审阅分别报告，不把“创建文件成功”算作全部通过。
