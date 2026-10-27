# S22/S23 部署准备交接 — 2026-10-27

已修复已复现的部署配置缺口；**未部署，未完整运行有数据网站**。

- 基线：`89cf2ab3db1b32117dcefbda581fcb36c1828240`
- 云端分支：`task/deployment-s22-s23-89cf2ab`
- 本地提交：`c817727ca8000bd1b19daae606196681fd29c50e`
- 助手身份：`Codex <codex@openai.com>`
- 仅4个文件：`website/compose.yaml`、`website/Dockerfile.api`、`website/README.md`、`website/tests/test_deployment_contract.py`。

## 最新上游同步

已拉取 `main` 的 `89cf2ab3db1b32117dcefbda581fcb36c1828240`（仅4份文档，87行新增）。在新独立分支重新应用原部署补丁；仅website/README.md发生文本位置冲突，保留上游交接链接及完整部署说明后解决。Compose、Dockerfile和测试与原补丁逐字一致，上游docs内容未改。原分支、原提交ac340732和旧ZIP仍保留；本ZIP替换Library当前版本，不重复应用旧补丁。

本轮重跑148测试、静态Compose和223局离线预检通过。最初复跑因稀疏工作区遗漏仓库已有的S23复核进度与照片验收JSON而失败；恢复该受版本控制文件后全部通过，非源码修复。上游交接文档中的“尚无补丁交付”、144测试等是此前快照；最新本补丁和148测试以此包为准。未把仓库中的自动同步文字视为dot推送权限。

## 修改

Compose补齐S22/S23正式JSON和投票旁证只读挂载，默认全量发布；增加显式悍跳发布工具，并挂载/app/config，保留实际发布器的完整局数校验。API镜像补入bluff-frames截图。说明顺序为全量正式发布 → 两季悍跳预检及分别发布 → 既有grant_reader脚本 → 只读API运行。

没有修改用户电脑、正式数据、schema、共享config、workflow或依赖锁。没有推送、合并、部署、创建角色、设置凭据或操作数据库安全配置。

## 应用补丁（用户在获准独立工作区执行）

确认工作区干净、基线正确，先审阅补丁。以下仅创建本地分支/提交：

```sh
git status --short
git rev-parse HEAD
# 预期 89cf2ab3db1b32117dcefbda581fcb36c1828240
git switch -c review/deployment-s22-s23 89cf2ab3db1b32117dcefbda581fcb36c1828240
git apply --check /path/to/0001-prepare-s22-s23-deployment.patch
git am /path/to/0001-prepare-s22-s23-deployment.patch
```

若基线不同，先人工复核兼容性，不要强行应用。接收机器git am生成的提交ID可能不同。

## 已验证

- **148 passed，2 deselected**：144个既有纯/mock测试 + 4个新部署契约测试；另整文件排除4个真实DB API测试，共6个数据库测试未执行。
- **Compose v2.39.4静态config --quiet通过**；假值插值，没有调用daemon。
- **223局离线预检通过**：148 S22 + 75 S23，2676座位、700轮、525票型、3813票。release指纹未改变：`S22_S23-1c2312637b4dd6b8-805e6171-p4-s2`。
- 新测试按Compose实际挂载复制临时源，对比完整预检哈希；覆盖两季CLI、账号隔离与截图文件。无需Windows符号链接权限。基线S23投票旁证目录不存在，发布器允许为空；测试未向源树创建目录。
- 第二位助手只读复核通过；已修正验收URL环境变量说明和Windows测试兼容性。diff检查与补丁反向应用检查通过，提交后工作区干净。

### 安全验证复跑

项目根目录，按仓库说明准备Python测试依赖。Windows用`.\.venv\Scripts\python.exe`替换python，并以PowerShell方式设置仅用于静态校验的假环境变量。

```sh
python -m pytest website/tests -q --ignore=website/tests/test_api.py -k 'not test_publish_failure_does_not_change_active_release and not test_publish_is_idempotent_and_can_leave_active_pointer_unchanged'
python -m website.api.publish --seasons S22 S23 --check
# POSIX shell，仅静态配置校验：
POSTGRES_PASSWORD=static-validation-only POSTGRES_READER_PASSWORD=static-validation-only docker compose -f website/compose.yaml config --quiet
git diff --check
```

## 目标环境仍需验收

完整部署命令在补丁的website/README.md。获得部署/数据库授权后才执行写操作。悍跳两季不是跨季原子事务；既有账号的历史授权、成员关系、继承和PUBLIC权限必须管理员审查，grant_reader不是角色清理器。

真实数据库准备且获准后，在项目根运行以下验收；DB测试会使用临时schema，仅限专用获准环境：

```sh
python -m pytest website/tests -q
# 先设置MASTERS_API_URL、MASTERS_WEB_URL为获准且可达的目标地址：
python website/check_publication.py --seasons S22 S23 --api-only
python website/check_publication.py --seasons S22 S23
```

API未发布宿主机端口，验收程序必须有获准的内部API网络访问，不能默认localhost:8000可达，不为验收擅自开放公网端口。浏览器验收需目标环境安装仓库声明的Playwright浏览器。目标需核对两季局数/悍跳绑定、照片、102张基线S23截图、桌面/手机页面及备份恢复。

## 未运行与边界

云环境Docker daemon、PostgreSQL服务端socket与浏览器启动受限，未绕过限制。Docker镜像构建/容器运行、真实数据库发布/迁移/角色授权、真实API集成、完整有数据网站和浏览器视觉验收均**未运行**。

前端此次未改。先前基线复现已有typecheck、生产构建及无API时HTTP错误壳通过，不代表有数据网站可用。原始复现证据保留在助手工作区reproduction-latest/，未混入源码。本包仅含补丁、交接说明和本次安全验证记录，无凭据、数据库内容或图片资产，未对外共享。
