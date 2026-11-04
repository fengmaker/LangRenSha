# GitHub Pages 静态发布执行方案

更新日期：2026-11-04。适用目录：`D:\langrensha`。

本文确定首版的实现与操作顺序：本地完成数据整理、正式发布、静态导出和构建；GitHub Pages 只部署已经验收的网页成品。沿用现有 Python、PostgreSQL、Next.js 和人工复核流程。

**当前状态：执行文档已整理，仓库内静态化代码尚未实现；本次未创建发布仓库或上线。** 下文标为“拟新增”“拟修改”的脚本、参数和配置属于开发任务，完成对应里程碑后才能执行。本文不代表已经完成数据入库、正式发布、commit、push 或部署。

数据准备继续按[赛季数据全流程](01_赛季数据全流程.md)和[增量更新流程](08_增量更新流程.md)执行；本地现有运行方式见[网站手册](../website/README.md)。

## 一、固定首版选择

| 项目 | 本方案采用的方式 |
| --- | --- |
| 开发与数据仓库 | 现有 `fengmaker/LangRenSha`，只使用 `main` |
| 发布仓库 | 拟新建公开仓库 `fengmaker/langrensha-site`，只使用 `main` |
| 发布仓库内容 | `site/` 静态成品、Pages 工作流、必要说明 |
| 预计网址 | `https://fengmaker.github.io/langrensha-site/`，以实际 Pages 设置为准 |
| 数据与统计 | 从本地已发布 API 导出最终公开响应，复用现有 Python 计算 |
| 前端 | 同一套 Next.js 页面和组件，保留本地维护模式，增加静态构建模式 |
| 首版上线触发 | 推送成品后手动运行工作流；源码仓库推送不触发公开站部署 |
| 日常构建 | 一个本地命令完成导出、构建和自动验收，成功后生成待发布目录 |
| 回退 | 在发布仓库撤销有问题的成品提交，再手动部署 |

独立发布仓库是工程选择，便于区分网页成品与加工资料；GitHub Pages 本身不要求另建仓库。项目站点的仓库名构成网址路径前缀，改名时必须同步修改 `basePath` 并重新构建。[GitHub Pages 站点类型](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

首版保留手动上线，避免同时改变本地维护、成品提交和上线触发三个环节。后续如需“推送发布仓库即上线”，只调整发布工作流触发方式。

## 二、功能范围与数据处理

| 功能 | 静态版实现与验收要求 |
| --- | --- |
| 首页、赛季页 | 构建时生成 HTML，数量与赛季从本次快照读取 |
| 对局列表 | 轻量索引；浏览器筛选、排序和分页 |
| 关键词、赛季、阶段、版型、选手、日期筛选 | 保留现有语义、默认值和 URL 参数 |
| 对局详情 | 逐局生成 HTML，保留座位、日夜、票型、终局、来源与待核说明 |
| 选手索引 | 每季导出完整索引，浏览器搜索和分页 |
| 选手个人页 | 构建基本资料；按所选赛季区间读取预计算统计 |
| 全季积分榜、决赛周榜 | 按各季实际支持的阶段预计算，保留既有计分规则 |
| 单季及跨季统计 | 导出全部已发布赛季的连续区间 |
| 最低出场次数 | 保留任意非负整数输入，在完整排名数据上筛选并更新名次 |
| 最低有效场次 | 保留现有榜单弹窗的筛选功能，与最低出场次数区分 |
| 悍跳证据与结论 | 公开页只读；保留人工确认、推断、待定、冲突等状态 |
| 维护者草稿、反馈导入与导出 | 保留在本地维护端，公开构建隐藏维护控件 |
| 照片、证据截图 | 输出清单允许且实际引用的实体文件 |

跨季范围从本次活动发布的真实赛季生成，不把 S21/S22/S23 写成永久规则。若只有这三季，范围为 `S21–S21`、`S22–S22`、`S23–S23`、`S21–S22`、`S22–S23`、`S21–S23`，共六种；有 N 个已发布赛季时为 N(N+1)/2 种。`latest` 在本次快照内解析为最新已发布赛季。

每位选手在每个区间的统计继续通过现有 Python/API 计算，区间内没有出场时沿用现有空数据语义。**跨季统计按原始分子、分母聚合，不平均各季胜率，不把未复核悍跳转换成 0。** 保留积分适用范围、未知结果、分母排除和证据关联。

## 三、开发顺序与阶段交付

按以下顺序推进；前一阶段通过后再扩展范围。开发过程直接在现有 `main` 上进行。

| 阶段 | 工作内容 | 通过条件 |
| --- | --- | --- |
| A：最小完整样例 | 版本元数据、单季导出、首页、列表筛选、一局详情、一位选手页、图片与子路径 | 样例静态产物可直接打开和刷新；浏览器阻断 API 后仍可操作 |
| B：全部已发布数据 | 全部分页、全部详情、选手、区间、榜单、统计、证据 | 数量、唯一 ID、区间和引用完整；与本地 API 对照一致 |
| C：完整静态前端 | 全部路由、URL 状态、排名筛选、公开只读与本地维护模式 | 静态构建通过，关键浏览器流程通过，本地草稿流程仍正常 |
| D：构建与验收入口 | 三个拟新增脚本、失败保留机制、现有 CI 扩展 | 单命令生成通过验收的完整成品，失败不覆盖上一份合格产物 |
| E：Pages 上线 | 发布仓库、工作流、成品推送、手动部署、线上检查 | 正式子路径下的首页、详情、筛选、统计、图片与手机访问正常 |

阶段 A 的样例必须在清单和报告中标为 `partial`，开发阶段样例不能进入正式发布仓库。完整发布要求覆盖当前活动发布的全部赛季和全部对局。

## 四、导出器与版本一致性

### 4.1 拟新增文件与接口

| 位置 | 职责 |
| --- | --- |
| `website/export_static.py`（拟新增） | 从已发布 API 导出完整公开 JSON、检索索引和引用图片 |
| `website/check_static.py`（拟新增） | 结构检查、API 对照、静态产物浏览器验收；复用现有验收代码 |
| `website/build_static.py`（拟新增） | 顺序调用导出、构建和验收，只在全部成功后更新待发布目录 |
| `/api/v1/export-manifest`（拟新增只读接口） | 返回有效 game release、各季悍跳发布标识、有效媒体清单指纹与统计版本 |

API 只读元数据从现有发布表和有效清单读取，无需另建发布数据库。各季悍跳直接使用现有 `publication_id`、`payload_hash`；未发布的季明确返回空值。已有发布数据存在但读取失败时必须报错，不按“尚未发布”处理。

### 4.2 固定同一份来源

现有 game release 与各季悍跳发布分别管理；同一 game release 下可以更新悍跳发布。只检查 `/api/v1/releases` 无法发现全部变化。照片清单也有进程缓存，代码或清单更新后先重启本地 API。

导出前后均读取有效元数据，并逐个核对响应中的 `release_id`；涉及悍跳的响应同时携带、核对其实际使用的复核发布标识，跨季响应记录所选各季标识。新增字段必须同步更新响应模型，避免被 Pydantic 丢弃。

首版采用单人维护窗口：从导出开始到 API 对照结束，暂停 game release、悍跳发布及照片／截图清单切换，避免中途切换后又切回而逃过首尾核对。无需增加跨系统锁或自动重试框架。

建议公开 `data/manifest.json` 至少包含：

| 字段 | 内容 |
| --- | --- |
| `schema_version` | 静态数据结构版本 |
| `snapshot_id` | 本次完整数据快照标识，不仅使用 game release ID |
| `build_id` | 本次构建标识，由构建入口补齐 |
| `release_id`、`source_hash` | 当前 game release 与已发布来源哈希 |
| `analytics_version` | 本次 API 实际使用的统计版本 |
| `bluff_publications` | 各季复核发布 ID、payload 哈希；无发布时为 null |
| `media_manifest_hashes` | 本次有效照片、截图清单的指纹 |
| `generated_at`、`base_path` | 含时区的生成时间与构建路径前缀 |
| `seasons`、`ranges` | 实际赛季、全部连续区间及可用阶段 |
| `counts`、`complete` | 实际导出数量、全量完成状态 |

构建回执另存源码 commit、工作区是否有未提交修改、构建输入指纹、依赖锁文件哈希、产物哈希和验收结果。源码存在未提交修改时如实记录，不把 commit 当成本次全部输入。回执不包含环境变量值、凭据或原始 diff，不复制进公开 `site/`。

### 4.3 导出顺序

1. 检查 API 健康及活动发布，记录有效元数据；赛季从活动发布读取。
2. 遍历 `/games` 的全部分页，核对 total、无重复 ID、完整数量与赛季覆盖。
3. 逐季遍历 `/players` 全部分页；合并选手 ID，生成全部选手详情路由清单。不能只导出默认赛季的选手。
4. 逐局读取详情的最终公开响应，保留派生阵营、presentation、timeline、票型和终局信息；不直接复制原始 `data/games` 替代它们。
5. 逐季导出全季／受支持的决赛周榜；逐区间导出统计，以及每位选手门槛为 0 的完整个人统计和排名数据。
6. 每季一次读取 `bluff-review?status=all`，保留全部公开条目；状态与选手筛选放在浏览器执行。summary 的统计范围仍按现有 API 定义，不能直接按可见条目重算。
7. 导出与现有 `search_text` 等价的轻量检索串，包括对局编号、BV、日期、版型和选手名。当前响应缺少必要字段时补公开只读字段，复用现有检索串生成规则；不扩大为转写全文搜索。
8. 从最终响应收集照片和截图引用，经现有白名单 API 读取字节，核验存在性、内容哈希与文件名。已有合法空照片保持空值；已引用图片缺失则导出失败。
9. 再次核对有效元数据与各响应绑定，完成 JSON、数量和媒体引用检查后才标记完整快照。

保存单份快照的目录约定如下。构建入口将其中 `data/`、`media/` 同步到前端专用生成目录；这些生成文件纳入 Git ignore，不提交到源码仓库。

```text
snapshot/
  data/
    manifest.json
    releases/<snapshot_id>/
      overview.json
      games/index.json
      games/<game_id>.json
      players/index.json
      players/by-season/<season>.json
      players/<player_id>/<start>--<end>.json
      leaderboards/<season>/<phase>.json
      stats/<start>--<end>.json
      bluff-review/<season>.json
  media/
    player-photos/<season>/<content-hash>.<ext>
    bluff-frames/<season>/<content-hash>.png
```

单份成品只包含本次完整快照，历史通过发布提交回退，不默认累积历次全量数据。先复用 API 响应结构；只有实际测量发现重复榜单显著影响体积或加载时间时，再拆分同一区间共享数据。

## 五、前端与本地维护端改造

### 5.1 保留一个明确的构建模式开关

拟修改 `website/web/next.config.ts`，参考配置如下。`NEXT_PUBLIC_SITE_MODE` 默认走本地维护模式；由构建入口仅在子进程中设置静态模式，避免污染日常运行环境。

```typescript
import type { NextConfig } from "next";

const staticSite = process.env.NEXT_PUBLIC_SITE_MODE === "static";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  output: staticSite ? "export" : "standalone",
  trailingSlash: staticSite,
  basePath: staticSite ? (process.env.NEXT_PUBLIC_BASE_PATH ?? "") : "",
  images: { unoptimized: true },
};

export default nextConfig;
```

静态模式通过 `next build` 生成 `out/`，Server Components 可以在构建阶段读取快照并生成 HTML。[Next.js 静态导出](https://nextjs.org/docs/app/guides/static-exports)

本地默认仍由 `website/run.py` 启动 API 与前端；`--production` 继续使用 standalone。保留一套展示组件，仅在数据读取和维护控件入口区分模式，不复制整套页面。

### 5.2 数据、路由与查询参数

- 本地维护模式继续通过现有 `src/lib/api.ts` 请求 API；静态构建的服务端读取模块从导出文件取数据，浏览器模块只 fetch 本站静态 JSON。文件系统读取模块不进入客户端包。
- 首页、赛季页、对局详情、选手基本资料构建为 HTML。查询参数控制的筛选、分页、区间统计由局部 Client Components 处理，保留静态外壳。
- `games/[id]`、`players/[id]`、`seasons/[id]` 用实际清单提供 `generateStaticParams()`。S23 专属悍跳路由只枚举当前确实支持的季；保留既有 `/leaderboard/bluff-review` 入口与链接。
- 静态分支及其 `generateMetadata()` 不读取请求时的服务端 `searchParams`；客户端 `useSearchParams()` 配置必要的 `Suspense`，并用生产构建验收。[useSearchParams](https://nextjs.org/docs/app/api-reference/functions/use-search-params)
- 查询变化后 URL 与显示同步；前进、后退能恢复筛选；筛选改变时按现有规则复位页码，超范围页码在客户端归一化。
- 对局排序保持日期降序、局号降序且未知局号最后、ID 稳定排序；保留 API 的筛选边界与关键词语义。
- 公开页不渲染反馈填写、保存、导入、导出控件；本地模式保留现有草稿存储键、反馈格式和证据指纹。

### 5.3 最低出场次数与排名

导出 `minimum_appearances=0` 的完整榜单，每行保留 `appearances`、原始 `rank`、排序和样本信息。浏览器按当前区间总出场次数筛选，沿用源 rank 分组更新名次、总人数与并列状态。

现有 `metric-rank.tsx` 已有按源 rank 分组重排的逻辑，可在局部复用。不得用展示用小数反推排名，也不能只过滤行而沿用旧名次。个人指标卡、角色／版型排名和弹窗必须同时反映门槛；选手被排除时保留其统计，显示未达门槛。

最低出场次数与最低有效场次是两个条件：前者决定参与排名的人群，后者沿用各指标已有的有效场数口径，两者可叠加。验证包含并列、无有效样本、门槛超过全部选手，以及有效场数与出场次数不同的情况。

### 5.4 图片与路径前缀

本地和静态模式统一使用 `public/media` 中清单允许的实体文件，移除当前同路径的两个媒体代理 Route Handler，避免与 public 文件冲突。资产同步复用导出器的媒体读取函数；本地启动在 API 就绪后准备媒体文件，standalone 启动还需将 `public/` 复制到 standalone 运行目录。图片更新不改变正式事实数据。

| 使用位置 | 路径要求 |
| --- | --- |
| Next `<Link>` 与框架导航 | 保持站内路径，由框架添加 basePath |
| 原生 `fetch`、`img`、媒体原图链接 | 使用公共路径函数添加一次 basePath |
| `next/image` | src 也需要带 basePath；静态模式关闭运行时优化 |
| 原生表单 action、站内 `<a>`、CSS `url()`、图标与 metadata URL | 逐项核对前缀 |
| 外部视频链接、页内锚点 | 保持原语义 |

basePath 在构建时写入产物，修改后需重新构建。[Next.js basePath](https://nextjs.org/docs/app/api-reference/config/next-config-js/basePath)

## 六、构建入口、验收与现有 CI

### 6.1 拟新增统一命令

以下命令仅在阶段 D 完成后可用，退出码非 0 表示本次失败：

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe website/build_static.py --api-url http://127.0.0.1:8000 --base-path /langrensha-site --output tmp/pages-preview/langrensha-site
if ($LASTEXITCODE -ne 0) { throw "静态构建或验收失败，本次成品不得发布" }
```

实现顺序：

1. 在 `tmp/pages-build/` 新建本次候选目录，导出并核对来源。
2. 同步候选数据和媒体到前端专用生成目录，只操作明确归属本流程的目录，不清理其他 public 文件。
3. 给前端子进程设置静态模式和 basePath，构建后完成类型检查；复用项目已有 Node 定位方式，Windows 使用 `npm.cmd`。
4. 对 `out/` 执行结构检查、API 对照和自动浏览器验收。
5. 全部通过后更新 `tmp/pages-preview/langrensha-site/`，将对应构建回执写入 `tmp/pages-preview/acceptance.json`；失败保留上一份合格目录及其回执，并在本次候选目录记录失败步骤与 build ID。

候选输出、合格成品和回执按 build ID 关联。`website/web/out/` 是中间产物；公开同步始终从合格目录读取。构建入口不自动执行数据发布、Git 操作或 GitHub 部署。Windows 执行构建前先结束本项目的 Next 前端，避免共享 `.next` 被占用；已经运行的本地 API 可继续用于导出。

静态构建会复用 `.next` 工作目录。之后启动本地开发模式可直接使用 `website/run.py`；若要运行本地 `--production`，先按默认本地模式重新执行 `npm.cmd run build --prefix website/web`，生成对应 standalone，不能将静态构建当成本地生产构建。

### 6.2 验收职责与通过条件

`check_static.py` 拟定接口：`--out <静态目录> --base-path /langrensha-site --api-url http://127.0.0.1:8000`。统一构建入口必须提供 API 地址并完成以下三层检查，不能用结构检查替代浏览器操作。

| 层次 | 必须检查的内容 |
| --- | --- |
| 文件与数据 | 清单完整标记、全量分页数量、唯一 ID、路由覆盖、全部区间、JSON 和媒体引用、内容哈希、产物大小 |
| API 对照 | 原始导出响应与绑定版本；代表性筛选的有序 ID、总数和分页；各区间统计；榜单全季／决赛周语义；门槛 0、非零门槛及边界排名 |
| 浏览器 | 在真实子路径挂载候选目录；详情直达及刷新；筛选和前进后退；个人页区间及排名弹窗；照片和截图；桌面与手机；阻断 API 后重载并操作 |

浏览器层复用现有 Playwright 验收逻辑，新增检查静态 JSON 和媒体请求失败、控制台异常、动态 API 请求；API 对照由 Python 进程完成，不依赖浏览器访问 API。结果与缺口写入本地回执，不将日志、截图或数据库备份复制到公开目录。

GitHub Pages 发布站点最大 1 GB，月带宽有 100 GB 软限制；验收测量最终成品，报告 JSON、页面和媒体体积。首次上线同时测量实际加载情况，再决定是否压缩图片或拆分数据。[GitHub Pages 限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)

开发回归至少覆盖：分页完整性、复核单独更新时拒绝混合快照、引用图片缺失、失败保留前次成品、跨季区间完整性、排名并列与两个门槛叠加。本地维护端验证草稿保存、导入和导出。

### 6.3 现有流程适配

- `website/run.py` 保留本地 API、开发前端和 standalone；只补实体媒体准备与 public 复制，不改成静态预览服务器。
- `.github/workflows/full-acceptance.yml` 与 `website/ci_acceptance.py` 保留现有数据库发布、只读权限、语义测试和本地站验收；在同一临时数据库上增加静态构建与子路径验收。
- 现有 CI 稀疏检出只覆盖 S22/S23，新增静态验收必须明确这一范围，不能声称覆盖三季。首次实际发布另外验收当前活动发布的全部赛季；只有扩展 CI 目标范围时才补 S21 及直接依赖资料。
- 新增 CLI 和 CI 命令兼容 Windows 与 Linux；CI 证据继续沿用现有受限上传目录。首轮迁移完成后跑一次网站语义回归及两个模式的完整验收，日常按改动范围验证。
- 更新 `website/README.md`、前端手册、脚本说明及生成文件 ignore，清楚区分本地维护、静态构建和公开部署。

## 七、开发完成后的本地执行

### 7.1 一次性依赖准备

复用现有 Python 虚拟环境、Node 和已安装依赖；缺少依赖时执行。依赖未变化且安装完整，日常无需重复安装。

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe -m pip install -r requirements/web.txt "pytest>=8,<9" "playwright==1.61.0"
if ($LASTEXITCODE -ne 0) { throw "Python 依赖安装失败" }
.\.venv\Scripts\python.exe -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "验收浏览器安装失败" }
npm.cmd ci --prefix website/web
if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败" }
```

浏览器验收统一使用 Playwright Chromium；后续调整版本时与现有 CI 同步。Node 复用项目现有安装与锁文件，不在本次任务中升级框架。

### 7.2 准备已发布 API

如果本地 API 已运行且代码、媒体清单没有更新，直接复用。否则在一个 PowerShell 窗口启动：

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe scripts/local_postgres.py start
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 启动失败" }
.\.venv\Scripts\python.exe -m uvicorn website.api.app:app --host 127.0.0.1 --port 8000
```

保留窗口。若数据已正式发布，静态导出无需再次入库或发布。尚未发布的数据按全流程及本次另行明确的授权范围处理，不能为了构建网页顺带切换数据库版本。

### 7.3 完整构建

阶段 A–D 完成后，在另一个 PowerShell 窗口执行：

```powershell
Set-Location D:\langrensha
Invoke-RestMethod http://127.0.0.1:8000/health -ErrorAction Stop
Invoke-RestMethod http://127.0.0.1:8000/api/v1/export-manifest -ErrorAction Stop
.\.venv\Scripts\python.exe website/build_static.py --api-url http://127.0.0.1:8000 --base-path /langrensha-site --output tmp/pages-preview/langrensha-site
if ($LASTEXITCODE -ne 0) { throw "静态构建或验收失败" }
```

成功后读取 `tmp/pages-preview/acceptance.json`，确认 `complete=true`、全部验收通过、赛季与范围正确；核对回执的 build ID 与成品 manifest 一致。

### 7.4 人工预览

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1 --directory tmp/pages-preview
```

打开 <http://127.0.0.1:4173/langrensha-site/>。合格目录已按项目子路径放置，无需再镜像一份预览文件。

人工确认首页数量与更新时间；每季一局详情的新标签直达及刷新；搜索、分页和前进后退；一位跨季选手的区间、门槛和排名弹窗；全季与决赛周榜；证据状态、照片与截图；手机阅读与操作。可停止本次专门启动的 API 后再刷新，验证公开网页独立运行。

## 八、首次配置 GitHub Pages

仅在完整静态成品和本地验收通过后进行本节。以下为实施时的操作步骤，本文交付时没有执行。

### 8.1 创建并克隆发布仓库

在 GitHub 的 `fengmaker` 账号创建公开仓库 `langrensha-site`，添加 README，默认分支为 `main`。已存在同名专用仓库时直接复用；若换名，先同步修改构建 basePath。

```powershell
Set-Location D:\
git clone https://github.com/fengmaker/langrensha-site.git
if ($LASTEXITCODE -ne 0) { throw "发布仓库克隆失败" }
```

发布仓库 README 记录站点用途、源码仓库、手动部署入口与回退方式，不复制本地加工资料。

### 8.2 添加发布工作流

在发布仓库创建 `.github/workflows/deploy-pages.yml`：

```yaml
name: Deploy static site to Pages

on:
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: github-pages
  cancel-in-progress: false

jobs:
  deploy:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Checkout published files
        uses: actions/checkout@v7.0.1
        with:
          persist-credentials: false
          fetch-depth: 1
      - name: Check static entrypoints and manifest
        run: |
          test -f site/index.html
          test -f site/404.html
          test -d site/_next
          python - <<'PY'
          import json
          from pathlib import Path
          root = Path('site')
          manifest = json.loads((root / 'data/manifest.json').read_text(encoding='utf-8'))
          assert manifest['complete'] is True
          assert manifest['base_path'] == '/langrensha-site'
          assert manifest['snapshot_id'] and manifest['build_id']
          assert sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) < 1_000_000_000
          PY
      - name: Configure Pages
        uses: actions/configure-pages@v6.0.0
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v5.0.0
        with:
          path: site
          retention-days: 1
      - name: Deploy to Pages
        id: deployment
        uses: actions/deploy-pages@v5.0.1
```

工作流只部署 `site/`，不运行数据库、导出器或 Next 构建。部署权限、artifact 和 environment 按 [GitHub 自定义 Pages 工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)配置。大小检查采用低于 1 GB 的十进制阈值，与本地验收保持一致。

模板版本已于文档更新日核对官方 release：[checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)、[configure-pages v6.0.0](https://github.com/actions/configure-pages/releases/tag/v6.0.0)、[upload-pages-artifact v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0)、[deploy-pages v5.0.1](https://github.com/actions/deploy-pages/releases/tag/v5.0.1)。正式维护可沿用项目现有完整 SHA 固定方式，升级时核对对应 release。

### 8.3 同步合格成品

确认合格目录是本次预览通过的 build ID。以下 `/MIR` 会删除目标中的旧成品，只能用于专用 `site/` 子目录；先核对发布仓库、分支和绝对目标路径。

```powershell
$publishRoot = (Resolve-Path -LiteralPath 'D:\langrensha-site' -ErrorAction Stop).Path
if ($publishRoot -ne 'D:\langrensha-site') { throw "发布仓库路径不符" }
$publishOrigin = git -C $publishRoot remote get-url origin
if ($LASTEXITCODE -ne 0 -or $publishOrigin -ne 'https://github.com/fengmaker/langrensha-site.git') { throw "发布仓库 origin 不符" }
$publishBranch = git -C $publishRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $publishBranch -ne 'main') { throw "发布仓库必须在 main" }
$publishTarget = [System.IO.Path]::GetFullPath((Join-Path $publishRoot 'site'))
if ($publishTarget -ne 'D:\langrensha-site\site') { throw "成品目标路径不符" }
if (Test-Path -LiteralPath $publishTarget) {
  $publishItem = Get-Item -LiteralPath $publishTarget -Force
  if (-not $publishItem.PSIsContainer -or ($publishItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw "成品目标必须是普通目录" }
}
$readySite = (Resolve-Path -LiteralPath 'D:\langrensha\tmp\pages-preview\langrensha-site' -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $readySite 'index.html'))) { throw "找不到合格静态首页" }
$readyManifest = Get-Content -LiteralPath (Join-Path $readySite 'data/manifest.json') -Raw | ConvertFrom-Json
if ($readyManifest.complete -ne $true -or $readyManifest.base_path -ne '/langrensha-site') { throw "快照不完整或路径不符" }
robocopy $readySite $publishTarget /MIR
if ($LASTEXITCODE -ge 8) { throw "成品同步失败" }
```

正确位置是 `site/index.html`、`site/_next/`、`site/data/manifest.json`、`site/media/`、`site/games/<id>/index.html`。**不再加一层 `site/langrensha-site/`**；网址中的前缀由 Pages 挂载。

### 8.4 提交、推送与手动上线

在实际获准提交、推送本次成品的范围内执行，每条成功后继续：

```powershell
Set-Location D:\langrensha-site
git status --short
git add site .github/workflows/deploy-pages.yml README.md
if ($LASTEXITCODE -ne 0) { throw "暂存失败" }
git diff --cached --stat
```

核对暂存内容及 manifest build ID，然后提交并推送：

```powershell
git commit -m "Publish verified static archive"
if ($LASTEXITCODE -ne 0) { throw "提交失败或没有待提交改动，请核对状态" }
git push origin main
if ($LASTEXITCODE -ne 0) { throw "推送失败" }
```

GitHub 仓库进入 **Settings → Pages → Build and deployment → Source → GitHub Actions**。随后进入 **Actions → Deploy static site to Pages → Run workflow → main → Run workflow**。手动工作流需存在于默认分支，执行者需要仓库写权限。[发布源设置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)、[手动工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

工作流成功后，从 Pages 设置或部署输出打开实际网址，复查首页、各季详情直达与刷新、筛选、跨季选手页、榜单、照片／截图及手机访问。核对线上 manifest build ID 与本地成品一致，并用日常使用的网络实测加载体验，再分享链接。

## 九、日常更新与回退

### 日常更新

1. 按既有流程整理和人工确认新增数据，在另行明确范围内完成入库及本地正式发布；纯网页改动无需再次发布数据库。
2. 重启有代码或清单更新的 API；暂停发布切换，执行第七节的统一构建命令。
3. 查看本次验收结果，预览受影响页面；覆盖相应统计、区间和证据依赖。
4. 按第八节将合格成品同步到发布仓库，核对后提交、推送并手动运行工作流。
5. 核对线上 build ID 和受影响路径，记录发布仓库提交及实际站点地址。

首版统一命令每次从当前已发布 API 导出，保证行为一致。只有实际构建耗时需要优化时，才增加经过版本核对的快照复用选项；无需一开始增加缓存失效或增量构建机制。

### 公开网页回退

先在发布仓库 `git log --oneline -5` 找到有问题的成品提交，确认它是独立的发布提交。在 `main` 对该提交执行 `git revert 实际SHA`，处理必要冲突后推送，再手动运行同一个部署工作流。回退后核对线上 manifest 与目标旧版本。

公开网页回退只恢复发布仓库成品，不回退正式 JSON、JCMS、game release 或悍跳发布。数据确需纠正时按原数据流程修正，再生成新的完整静态成品。

## 十、故障定位与完成标准

| 现象 | 优先检查 |
| --- | --- |
| 本地 dev 正常、静态 build 失败 | 服务端 searchParams、动态路由参数、Suspense、遗留媒体代理或其他运行时能力 |
| 首页可开但样式、图片或 JSON 404 | basePath、原生路径前缀、实体媒体、是否错误多套一层发布目录 |
| 点击详情正常、直达或刷新失败 | 是否真正生成详情 HTML、trailingSlash 和部署目录层级 |
| 少了旧季选手或对局 | 列表是否遍历全部分页，选手路由是否取各季并集 |
| 切换跨季后空白或回到默认季 | 全区间导出、latest 映射、URL 状态与客户端加载 |
| 筛选后名次或并列错误 | 是否更新排名人数和分组，是否误用展示小数，两个门槛是否混淆 |
| 个人统计与证据结论不一致 | game release、各季复核 publication ID、API 是否重启、是否在导出期间切换发布 |
| 本地维护图片或草稿功能受影响 | 媒体同步、standalone public 复制、模式开关、原草稿键与反馈指纹 |

完成时逐项记录实际结果：

- [ ] 全部活动发布赛季、对局、选手、连续区间及媒体完整，来源绑定一致。
- [ ] 核心筛选、分页、直达、刷新、排名及证据状态保持现有语义。
- [ ] 静态产物在实际子路径独立运行，浏览器没有动态 API 请求。
- [ ] 本地开发、standalone 与维护者草稿流程正常。
- [ ] 新增相关回归与现有必要检查通过，CI 报告说明实际覆盖范围。
- [ ] 合格成品与回执关联，失败保留上一份合格成品。
- [ ] 发布仓库只含公开成品和配置，线上 build ID 与部署提交可对应。
- [ ] 正式网址、桌面／手机、日常网络下的线上检查完成；实际未执行项明确列出。

当前起点是阶段 A。先完成可独立运行的完整样例，再扩展全部数据与验收；阶段 D 完成后，第七至九节才成为可重复执行的运行手册。
