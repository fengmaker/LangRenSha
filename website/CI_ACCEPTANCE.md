# S22 + S23 GitHub Actions 全链路验收（待首次真实运行）

这不是部署脚本，不操作线上网站或数据库。新增工作流 `Full S22 S23 acceptance`
在一次性 `ubuntu-24.04` runner 上启动与现有 Compose 相同的 `postgres:18-alpine`。
不使用 production secrets，不持久化数据库，不授予仓库写权限，不使用 `pull_request_target`。

## 运行条件与启动

需要仓库维护者具有推送 `.github/workflows` 的权限，并且仓库允许 GitHub Actions、
官方 `actions/*`、GitHub-hosted Ubuntu runner、Docker Hub、PyPI、npm、Playwright 下载。
可能消耗 Actions 分钟／存储额度；仓库策略或依赖下载失败不能当作应用验收通过。

在本机 Codex／有写权限的环境审阅并应用补丁后，可推送到专用分支 **`ci/full-acceptance`**，
该分支的 push 会自动运行（不需要先合并到默认分支）。或者工作流已在默认分支时，
进入 Actions → Full S22 S23 acceptance → Run workflow，选择要验收的提交分支。
不要为了运行而直接推送默认分支。此交付本身没有推送、触发、合并或部署。

## 实际检查顺序

1. 稀疏检出正式 S22/S23 JSON、投票旁证、config、scripts、website、测试报告夹。
   包含网站照片、悍跳图片与两季悍跳发布 JSON；排除多 GB 的 S21 帧、原始媒体及备份。
2. Python 3.12 + Node 22；`npm ci` 使用原锁文件；安装固定 Playwright 1.61.0 及 Chromium。
   网站 Python runtime 沿用原依赖范围，只增加 pytest/httpx；不引入采集／ASR 大依赖。
3. 正式发布预检，然后用现有发布器应用 **website/api/schema.sql** 并发布两季。
   网站不依赖 JCMS 业务迁移，不导入 JCMS 生产库。
4. S22/S23 悍跳各自预检并发布。任一命令非零即停止。
5. 执行全部 `website/tests`，JUnit 必须非空、零 skip/failure/error，且包含四个指定的
   数据库发布／API集成测试。不接受“数据库不可用所以跳过”的假绿。
6. 用现有 `grant_reader` 创建只读账号。核对 148 + 75 = 223 局、两季悍跳活动绑定、
   角色非管理员及表授权；将事务切成 READ WRITE 后仍须拒绝 UPDATE，避免仅测到只读默认值。
7. 启动只读账号 API、生产 build、前端 typecheck、启动前端。API 和页面各有 90 秒就绪期限；
   子进程及整作业也有期限，结束时清理进程。
8. 现有验收器逐一比较全部 223 局源文件与真实 API，检查 stats、两季悍跳绑定、照片哈希。
   Chromium 1440×1000 / 390×844 各检查 18 条页面路径；检查真实积分榜赛季／选手／局数、
   页面错误、不可用状态、横向溢出、统计范围，并等待照片实际解码。
   此为两种 viewport 布局检查，不声称真实手机／WebKit／Firefox 验收。

## 证据与隐私

Actions artifact `acceptance-<run>-<attempt>` 保留 7 天。只有指定目录内生成的 JSON、
日志和公开网页定尺寸 viewport 截图（不截取超长整页）；**不上传仓库源码、DB dump、环境文件、浏览器 trace、录像、cookies 或 storage state**。
日志及 JSON 在结束时移除 DSN、CI 两个账号密码及工作区绝对路径后，才复制到独立的上传目录。
测试 XML 不上传；强制取消若来不及整理证据，宁可不上传，也不上传未脱敏原始日志。
截图含网站公开比赛数据和选手海报；悍跳页面可含已获准公开的复核文字。
首次运行后仍应人工打开 artifact 审阅失败截图及内容再转发。

成功必须同时有绿色 job、`result.json` 的 passed、223 games、零跳过测试数、
`acceptance.json` 中 36 页面及两季照片覆盖。只看到日志文件或截图不代表通过。
失败时查看对应阶段 `.log` 和可能的 `screenshots/failure.png`。
依赖安装失败发生在生成证据之前时，查看 Actions 安装步骤日志。

## 本次已核验与尚未核验

- 本地 Python 编译、YAML结构检查、diff空白检查通过；新增防假绿/目标库保护/日志脱敏测试 8 项通过。
- 本地网站测试 **156 passed, 6 skipped**；六项依赖真实 PostgreSQL，未执行。
- Docker / PostgreSQL 真实发布、只读授权、完整 API、生产前端启动及浏览器尚未在本次云环境执行。
- 因连接器仅有 pull 权限，远端 Actions **尚未触发**。本地静态结果不能升级为全链路通过。

## 官方依据／固定 Action 版本

- [GitHub PostgreSQL service](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)
- [Playwright CI](https://playwright.dev/docs/ci-intro)
- [PostgreSQL 事务只读默认可被覆盖](https://www.postgresql.org/docs/current/sql-set-transaction.html)
- checkout v4.2.2: `11bd71901bbe5b1630ceea73d27597364c9af683`
- setup-python v5.6.0: `a26af69be951a213d495a4c3e4e4022e16d87065`
- setup-node v4.4.0: `49933ea5288caeca8642d1e84afbd3f7d6820020`
- upload-artifact v4.6.2: `ea165f8d65b6e75b540449e92b4886f43607fa02`

以上完整 SHA 已逐项从官方 GitHub release → commit 链接核实；不是浮动 major tag。
Postgres镜像及Python runtime范围沿用项目约定，未声称所有供应链组件均为不可变锁定。
