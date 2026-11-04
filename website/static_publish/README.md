# GitHub Pages 静态发布

本目录集中维护静态导出、构建、验收、同步脚本及发布仓库模板。日常只需运行 `sync_pages.py`，它会生成成品、提交推送发布仓库、等待 GitHub Actions 部署并核对线上版本。

## 在哪里修改

| 位置 | 内容与用途 |
| --- | --- |
| `D:\langrensha\website\web\src` | 网页布局、文字和交互的源码，在这里修改 |
| `D:\langrensha\website\api` | 本地接口与统计逻辑，在这里修改 |
| `D:\langrensha\data`、`config`、`website\assets` | 正式数据、规则及照片／截图来源，按原有流程维护和发布 |
| `D:\langrensha\website\static_publish` | 本说明、静态发布脚本和模板 |
| `D:\langrensha-site` | 独立发布仓库；`site/` 是生成结果，由脚本更新，手改可能被覆盖 |

流程为：**修改源码／正式发布本地数据 → 运行同步命令 → 生成静态成品 → 推送发布仓库 → GitHub Pages 自动更新**。GitHub Pages 只托管生成的 HTML、CSS、JS、JSON 和图片，不运行 Python 或数据库。

## 日常更新上线

所有命令均在项目根目录 `D:\langrensha` 的 PowerShell 中执行。

1. 完成网页或统计代码修改。数据修改需先按[赛季全流程](../../docs/01_赛季数据全流程.md)完成本地正式发布；脚本读取当前活动发布，不会自行入库或发布尚未生效的数据。
2. 确认本地 PostgreSQL 已运行，代码修改和数据发布均已结束；同步过程中不要切换活动发布或继续改源码。
3. 执行：

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe website/static_publish/sync_pages.py
```

脚本依次完成：

1. 在随机本地端口启动临时只读 API，使用现有数据库配置；构建结束后关闭它，不占用本地维护服务的端口。
2. 复用上一份合格成品中的未变响应和图片，导出最新完整快照。
3. 首次生成或网页源码变化时执行 Next 静态构建和类型检查；仅数据变化时复用已验收的网页程序，更新 JSON、媒体及详情地址。随后做文件、API 和小范围浏览器验收。
4. 将合格成品同步到 `D:\langrensha-site\site`，同时更新部署工作流和发布仓库 README；只写入有差异的文件，删除已失效的生成文件。
5. 在发布仓库 `main` 提交并推送，等待 GitHub Actions 部署成功，核对线上 manifest、首页及各季代表对局页。

命令以退出码 `0` 结束并输出 `Published ...` 后，本次线上同步完成。站点地址：<https://fengmaker.github.io/langrensha-site/>。无需再手动点击部署。

此命令只提交发布仓库的成品和模板，**不会提交或推送 `D:\langrensha` 源码仓库**。单独向源码仓库执行 `git push` 也不会更新 GitHub Pages。

### 首次使用的前提

当前电脑已具备这些条件，日常无需重复安装：

- Python 环境 `.venv` 可运行本地只读 API；默认浏览器验收需要 Playwright 和可用的 Chrome。使用 Playwright Chromium 时加 `--browser-channel chromium`，并先安装对应浏览器；显式跳过浏览器检查时不需要启动浏览器。
- Node/npm 可用，`website/web` 已执行 `npm ci`。Node 查找沿用本地网站启动器的 PATH／`.tools/node` 规则。
- PostgreSQL 和网站只读数据库配置可用。若数据库未启动，先执行 `.\.venv\Scripts\python.exe scripts/local_postgres.py start`。
- `D:\langrensha-site` 已检出发布仓库，origin 为 `https://github.com/fengmaker/langrensha-site.git`，当前分支为 `main`；Git 已配置提交身份及推送认证，仓库内没有独立的手工改动。
- 发布仓库 Pages 来源为 GitHub Actions。同步脚本会安装本目录中的自动部署模板；源码仓库的全量验收CI已移除，不影响此部署。

新电脑如尚未检出发布仓库，可先运行 `git clone https://github.com/fengmaker/langrensha-site.git D:\langrensha-site`。路径不同时，使用 `--publish-dir 实际路径` 指定。

## 只构建与预览，不上线

先按[网站启动说明](../README.md#启动)运行本地服务，确认 API `http://127.0.0.1:8000` 可用，再在另一个终端执行：

```powershell
.\.venv\Scripts\python.exe website/static_publish/build_static.py --api-url http://127.0.0.1:8000
```

成功后成品位于 `tmp/pages-preview/langrensha-site/`，该命令不提交、推送或部署。预览：

```powershell
.\.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1 --directory tmp/pages-preview
```

打开 <http://127.0.0.1:4173/langrensha-site/>，结束预览时按 Ctrl+C。

## 增量范围与常用选项

- 未变的对局、统计、榜单和悍跳响应按输入指纹复用，图片按内容哈希复用。赛季统计变化会影响相关区间全体选手的排名，不能只重算参赛者。
- 网页与数据分离：公开页面打开后读取本站静态 JSON。首次运行、网页源码／依赖／构建配置变化时编译网页程序；仅数据变化时复用合格成品的程序和页面模板，不执行 Next 构建。新增及删除对局、选手、赛季的地址由脚本按当前快照更新，详情网址保持原样。
- 源码输入、API 元数据及发布历史完全未变时，保留旧 build ID，跳过导出和网页构建；同步脚本仍核对发布及线上状态。上次显式跳过浏览器检查、本次使用默认命令时，会补做浏览器验收。
- 默认浏览器验收只访问关键入口及本次变化相关页面，并检查代表性的筛选、分页、区间与排名交互；不再逐条打开全站路由。文件覆盖、JSON、媒体哈希、API 与发布版本一致性检查继续保留。
- Git 推送复用已有对象；GitHub Actions 部署的是完整站点 artifact。
- `sync_pages.py --full`：不复用旧响应，重新完整导出并验收；网页程序未变时仍可复用，浏览器仍采用小范围验收。
- `sync_pages.py --skip-browser-check`：跳过浏览器检查，保留构建失败拦截、文件完整性及 API／版本检查。回执明确记录浏览器为 `skipped`，不将其记为已通过。
- `sync_pages.py --api-url http://127.0.0.1:8000`：复用指定 API，不另起临时 API，也不会关闭指定服务。
- `sync_pages.py --publish-dir D:\其他位置\langrensha-site`：指定发布仓库检出目录，仍须满足既定 origin 和 `main` 分支要求。

跳过浏览器验收并同步上线：

```powershell
.\.venv\Scripts\python.exe website/static_publish/sync_pages.py --skip-browser-check
```

只生成本地成品、跳过浏览器验收，不提交或上线：

```powershell
.\.venv\Scripts\python.exe website/static_publish/build_static.py --api-url http://127.0.0.1:8000 --skip-browser-check
```

公开页首次打开可能短暂显示加载状态；比赛内容、动态标题随后从当前快照读取。本地维护模式仍保留原有服务端取数方式。

构建回执的 `frontend_build` 区分 `compiled` 与 `reused`，`stage_seconds` 记录导出、编译、页面地址生成和验收的实际耗时；不要将首次全量导出的时间当作每次增量更新的固定用时。

## 文件与生成目录

| 文件／目录 | 用途 |
| --- | --- |
| `sync_pages.py` | 日常一键同步入口，包含提交、推送和部署后核对 |
| `build_static.py` | 导出、构建、验收，通过后替换本地合格成品 |
| `export_static.py` | 公开 API 快照和白名单媒体导出，供构建器及本地媒体准备复用 |
| `check_static.py` | 文件覆盖、版本绑定、API 对照和真实浏览器验收 |
| `templates/deploy-pages.yml` | 同步到发布仓库 `.github/workflows/deploy-pages.yml`；推送成品自动部署，保留手动入口 |
| `templates/published-README.md` | 同步到发布仓库根目录的说明模板 |
| `../web/.static-build/` | 独立编译工作目录；复用前端依赖，不影响维护服务的 `.next` |
| `../../tmp/pages-build/<build_id>/` | 候选快照、构建日志和失败回执 |
| `../../tmp/pages-preview/langrensha-site/` | 最新合格完整成品，也是下次增量更新的基线 |
| `../../tmp/pages-preview/acceptance.json` | 合格成品的构建来源、文件哈希、增量索引和验收结果 |
| `../../tmp/pages-preview/publication.json` | 发布提交、部署结果、线上核对或失败信息 |
| 合格成品中的 `.static-shells/` | 不含比赛数据的详情页模板，供新增地址和后续数据更新复用；不要手工修改 |

生成目录不放进本目录，不提交到源码仓库；公开发布仓库只接收成品与部署配置。保留最新合格成品和同级 `acceptance.json` 才能持续增量复用；删除后下一次恢复完整导出建立基线。网站共享组件和媒体原件仍在原有目录，本目录不另存一套。

## 失败和回退

- 导出、构建或上线前验收失败：停止，不推送成品，保留上一份本地合格成品和线上旧版。终端会给出原因，详细步骤见本次 `tmp/pages-build/<build_id>/receipt.json` 及相应日志；修复后重新执行同步命令。
- 推送、Actions 部署或线上核对失败：检查终端错误、`publication.json` 和[发布仓库 Actions](https://github.com/fengmaker/langrensha-site/actions)。超时不等于远端已取消，先确认工作流状态。
- 部署后核对失败时，新版可能已上线；脚本不会自动回滚。可修复后重发，或在发布仓库 `main` 用 `git revert` 撤销有问题的独立成品提交，再推送触发部署。

网页回退不回退本地正式数据或数据库活动发布。验收检查导出与展示是否一致、文件是否完整及代表交互能否使用，不代替比赛事实的人工复核。

架构、完整验收范围及既有上线记录见[静态发布执行方案](../../docs/11_GitHub_Pages静态发布执行方案.md)。
