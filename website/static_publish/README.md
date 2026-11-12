# 静态导出与显式上线

数据路径为：最终 game.json → 共用统计 → 静态 JSON → 同一套网站组件。全过程不启动数据库或 API，也不读取历史证据和反馈。

日常本地修改只需：

```powershell
.\.venv\Scripts\python.exe website/static_publish/export_static.py --check
.\.venv\Scripts\python.exe website/run.py
```

`--check` 只读校验最终数据与统计投影，不需要历史基线副本。`export_static.py` 无参数时写入 `website/web/public/data` 和正式照片媒体；可用 `--root`、`--output`、`--base-path` 指定本地目录。导出结果使用内容指纹，保留对局、选手、统计区间、榜单与共用排名的现有浏览器格式，不再生成悍跳公开复核数据。

只有用户明确要求构建/同步静态网站时才执行：

```powershell
# 只构建本地成品并检查
.\.venv\Scripts\python.exe website/static_publish/build_static.py
# 明确要求同步上线时执行
.\.venv\Scripts\python.exe website/static_publish/sync_pages.py
```

`build_static.py` 默认把成品写到 `tmp/pages-preview/langrensha-site`，使用 `/langrensha-site` 子路径；`--output`、`--base-path` 可调整。构建继续复用无数据的详情模板，再按当前清单生成对局、选手和赛季地址；结构校验与少量代表页面检查通过后替换本地合格成品。生成目录均忽略 Git，无需长期保留构建副本或验收回执。

`sync_pages.py` 已包含构建，无需先单独构建；`--check-only` 也会重新构建并检查本地成品。无该参数时同步现有独立发布仓库 `D:\langrensha-site` 的 `site/` 及部署模板，提交并推送发布仓库 main，然后核对部署状态与线上数据版本。发布目标为 https://github.com/fengmaker/langrensha-site，线上为 https://fengmaker.github.io/langrensha-site/ 。它与源码仓库的提交/推送是独立操作，日常本地修改不调用此命令。日常指令见[常用命令](../../docs/01_常用命令.md#同步静态网站)。

导出或构建失败时保留上一份合格成品；远端部署失败时报告具体错误，修复后重跑。网站历史数据的修订仍需先更新本地最终 JSON，再按授权同步。
