# Git协作入门

## 加入

仓库所有者在GitHub Settings → Collaborators中邀请成员，成员本人接受邀请。三人分别clone同一个仓库，在Obsidian中打开本地克隆目录；不要把它放进其他Git仓库内部。

## 命令行的一次普通资料提交

在本仓库目录执行：

```bash
git switch main
git pull --ff-only
git switch -c yourname/add-resource
# 编辑本次资料，保存文件
git status
git add 资源索引.md
git diff --cached
git commit -m "补充一项已阅读资源及使用说明"
git push -u origin yourname/add-resource
```

`yourname/add-resource`需改成自己的分支名，`git add`路径改成实际文件。随后在GitHub创建Pull Request，由另一人核对后合并。合并后切回main并pull，再开始下一次工作。

## GitHub Desktop

File → Clone Repository → 选择team-learning → Clone。修改前在main执行Fetch/Pull；Current Branch → New Branch；编辑文件后Commit，Publish branch，再Create Pull Request。互审与合并在网页完成。

## 常见状态

- 保存文件：还没有Git版本记录。
- Commit：本机有版本，其他人还看不到。
- Push：分支已上传GitHub。
- Pull Request：请求将分支合并到main，便于另一个人核对。
- Pull：把远程更新取回自己的电脑。

若pull失败、出现冲突或认证错误，保留错误信息再定位；不要使用force push或删除.git来绕过。
