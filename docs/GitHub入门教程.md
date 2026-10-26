# GitHub 新手入门教程（为本项目定制）

> 目标读者：从没用过 Git / GitHub，但已经能在电脑上跑 Python。
> 读完后你能：看懂项目里的 git 相关文件是干什么的，把自己的代码推上 GitHub，
> 并知道以后日常怎么用。全文 10 分钟能读完。

---

## 1. Git 和 GitHub 是什么关系？

- **Git**：装在你电脑里的"存档系统"。它把项目每次改动拍一个快照（叫**提交 / commit**），
  任何时候都能回看历史、撤销改动。项目文件夹里那个隐藏的 `.git/` 文件夹就是它的账本——
  **不要手动修改里面的东西**。
- **GitHub**：一个托管 Git 仓库的网站（微软旗下，对公开仓库免费）。
  把本地仓库"推"（push）上去，就得到了云备份 + 网页版历史 + 自动化部署入口。
- 一句话：**Git 是工具，GitHub 是存放工具成果的云端仓库**。
  类比：Word 是工具，OneDrive 是网盘——你用 Word 写文档，存到 OneDrive 备份分享。

## 2. GitHub 对这个项目的三个用处

1. **云备份 + 版本历史**：电脑坏了代码不丢；改坏了随时回滚到任意一天的版本。
2. **自动化**：仓库里的 `.github/workflows/update-dashboard.yml` 是 GitHub Actions
   定时任务。代码上了 GitHub 之后，它会在每个交易日 19:30 / 22:00（北京时间）
   自动更新数据、重建看板、并把新数据提交回仓库——**你从此不用手动跑更新脚本**。
3. **免费发布网页**：GitHub Pages（发布 `docs/index.html` 静态看板）和
   Render（实时渲染版）都要求代码在一个 Git 仓库里，GitHub 是最顺手的那个。

## 3. 你现在在哪一步？

项目已完成 git 初始化（此前替你做好的）：

| 项目里的东西 | 是什么 |
|---|---|
| `.git/` 文件夹 | Git 的账本本体（隐藏文件夹），记录了已有的 2 次提交 |
| `.gitignore` | "不上传黑名单"：列在里面的文件/文件夹 git 视而不见 |
| 两次提交 | `git log --oneline` 可以看到：初始版本 + Render 方案 |

还差的一步就是：在 GitHub 网站上建一个空仓库，然后 push（推送）上去。

## 4. 推送五步（约 10 分钟）

**第 1 步 · 建仓库**：登录 [github.com](https://github.com) → 右上角 **+** →
**New repository**：
- Repository name：例如 `hongli-lowvol`
- 选 **Public**（Pages 和免费版 Render 都要求公开仓库）
- **不要**勾选 "Add a README"（本地已有，勾了会产生冲突）
- 点 **Create repository**

**第 2 步 · 复制仓库地址**：创建后网页会显示一个地址，形如：

```
https://github.com/你的用户名/hongli-lowvol.git
```

**第 3 步 · 本地关联并推送**：在项目文件夹里打开 Git Bash，执行
（把地址换成你自己的）：

```bash
git remote add origin https://github.com/你的用户名/hongli-lowvol.git
git push -u origin main
```

**第 4 步 · 授权**：第一次 push 会自动弹出浏览器让你登录 GitHub 并点
"Authorize"——这是 Git for Windows 自带的凭据管理器，授权这一次以后永远免密。
如果它改成在命令行里问 Username / Password：Username 填用户名，Password 处要粘贴
**Personal Access Token**（GitHub → Settings → Developer settings →
Tokens (classic) → Generate new token，勾选 repo 权限）。
**这里输账号密码是无效的**，GitHub 的规定，不是你记错了。

**第 5 步 · 验证**：刷新 GitHub 网页，能看到全部文件即成功。
以后本地再提交过，只需执行 `git push` 一个词。

## 5. 以后日常怎么用？

改动代码之后的三连口诀：**装箱 → 贴标签 → 发货**：

```bash
git add -A                    # 装箱：把所有改动放进暂存区
git commit -m "一句话说明改了什么"   # 贴标签：拍快照，附上给人看的说明
git push                      # 发货：上传到 GitHub
```

不想用命令行也可以装 [GitHub Desktop](https://desktop.github.com)
（官方图形界面），点按钮完成同样的三步。

另外：部署好 Actions 之后，**每天的看板数据更新不需要你 push**——
机器人会自己提交，提交人显示为 `github-actions[bot]`。
你只需要在**改了代码**的时候手动三连。

## 6. 数据要不要和代码分离？（结论：不用，已经处理好了）

你的担心方向是对的，但这个项目的量级远没到需要担心的程度：

| GitHub 的限制 | 本仓库实际 |
|---|---|
| 单个文件超过 **100MB** 直接拒收 | 最大单文件约 6MB（一个回测报告 HTML） |
| 整个仓库建议 **1GB** 以内 | 被跟踪的 162 个文件共约 **53MB** |

- 真正的大块头 `_retired_2026-08-23/`（约 107MB 旧归档）已经写进 `.gitignore`
  排除——**文件还在你硬盘上，只是 git 不管它、不上传它**。
- `data/` 下两个行情 CSV 只有约 1.4MB，而且看板的"API 挂了就用仓库数据兜底"
  逻辑**依赖**这两个文件，它们应该留在仓库里，不算"乱占空间的数据"。
- 以后如果产生新的不想上传的大文件（比如临时导出），往 `.gitignore` 里加一行即可。

## 7. `_retired_` 文件夹是什么？

`_retired_2026-08-23/` 是 2026-08-23 重构项目时的**旧版本归档箱**：
被新代码替代的旧脚本、旧产物都挪进去封存，程序不会再用它，留作翻旧账用。
"107MB 的归档按体积排除在 git 外"的意思就是：这个文件夹写进了 `.gitignore`，
所以它**只存在于你的硬盘，不会上传到 GitHub**。
哪天你确认新版报告无遗漏，直接删掉整个文件夹即可，git 和程序都不受影响。

## 8. 命令小抄

| 想做什么 | 命令 |
|---|---|
| 看当前改动了什么 | `git status` |
| 看提交历史 | `git log --oneline` |
| 日常存档三连 | `git add -A && git commit -m "说明" && git push` |
| 放弃某文件未提交的改动 | `git checkout -- 文件名` |
| 查看某次提交改了哪些行 | `git show 提交号` |
| 把仓库复制到另一台电脑 | `git clone 仓库地址` |

## 9. 推上去之后，怎么让看板跑起来？

见 `docs/DASHBOARD_GUIDE.md`：
- 静态版：仓库 Settings → Pages → 选 main 分支 `/docs` 目录 → 得到
  `https://你的用户名.github.io/hongli-lowvol/`；
- 实时版：render.com 注册 → New Web Service → 连接这个仓库，`render.yaml`
  会被自动识别，一路确认即可。
- 两条线都以这个 GitHub 仓库为源头，**push 一次，所有云端功能都吃到最新代码**。

## 10. 两个安全提醒

1. 仓库是公开的，**任何密钥、密码、token 都不要提交进去**。
   本项目用的都是无需鉴权的公开 API，目前是安全的；以后加功能时保持这个习惯。
2. `.git` 文件夹不要手动编辑。误操作想反悔时，先 `git status` 看状态，再决定怎么办。
