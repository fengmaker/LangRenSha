# 静态导出与显式上线

数据路径为：最终 game.json → 共用统计 → 静态 JSON → 同一套网站组件。全过程不启动数据库或 API，也不读取历史证据和反馈。

日常本地修改只需：

```powershell
.\.venv\Scripts\python.exe website/static_publish/export_static.py --check
.\.venv\Scripts\python.exe website/run.py
```

`--check` 只读校验最终数据与统计投影，不需要历史基线副本。`export_static.py` 无参数时写入 `website/web/public/data` 和正式照片媒体；可用 `--root`、`--output`、`--base-path` 指定本地目录。清单记录当前发布版本，并把对局记录和按赛季生成的选手卡片映射到 `data/objects/<sha256>.json`。正文不变时可跨发布复用原地址。其余 JSON 仍按快照存放。

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

`sync_pages.py` 在部署成功且线上版本核验通过后，默认自动清理本地临时资料，无需另执行清理命令：

- 仅删除增量状态中已应用、正式文件哈希和媒体来源仍匹配的对局所对应的原始媒体、转写、截图与候选目录；清除这些已完成队列项。同赛季全部完成后再删除人工复核页、反馈和增量报告。
- 还有未完成对局时保留共用微博原件；全部完成后，先将已完整采集的微博日期覆盖和帖子 ID/日期合并到 `data/sources/weibo_checkpoint.json`，再删除对应原件。不完整微博窗口继续保留；当天尚未闭合的日期仍会在下次补扫。
- 删除本次本地成品、旧的已结束构建目录及静态构建工作区中重复的导出、公开数据和快照；保留本次 `result.json`、`sync-result.json`、正在构建的目录、正式照片、本地预览数据、依赖、模型、pytest 和 Next 编译缓存。其他用途的 `tmp/`、`.cache/` 文件不按日期批量删除。

只构建或 `--check-only` 不清理。发布或线上核验失败保留现场；构建后正式数据又发生变化也会保留临时资料。需要上线后保留临时资料排查时使用 `--keep-temp`。清理遇到占用或权限问题时终端显示简短提示，具体路径和原始错误记录在同步报告的 `cleanup` 中，网站上线结果仍按实际核验状态报告。公开数据的导出目录继承工作区权限，避免 Windows 下由沙箱账号生成的私有临时目录在移动后阻止普通终端清理；不重置其他目录的权限。

成品目录切换遇到 Windows `WinError 5/32` 时，会在约 6 秒内自动重试，覆盖扫描、索引等短暂占用；切换失败仍回滚并保留候选成品。持续占用或权限限制会报告具体目录和原始错误，需释放相关占用或修正权限后重试。

复用范围：直接读取现有正式 `game.json`；网站统计 JSON 每次重新计算并导出。详情页复用对局、选手、赛季三类编译模板，再按当前 ID 清单复制；每次仍执行前端构建和类型检查。同步发布仓库时，内容哈希相同的文件不重复写入。

终端默认只显示关键进度、构建与上线结果、总耗时和清理摘要，不再打印完整 JSON 或逐阶段计时。构建耗时仍保存在 `tmp/pages-build/<build_id>/result.json` 的 `timings_seconds`；完整同步还会写入同目录的 `sync-result.json`，包含文件同步、提交、推送、等待部署、线上核验、清理及总用时。中途失败也保留已执行阶段的耗时；下次成功上线清理旧构建后，仅保留最近一次的这两份小报告。

云端上传和部署分为两个依赖任务，产物按运行 ID 和上传任务的尝试次数命名；只重跑失败的部署任务时复用上传任务输出的产物名，避免重新上传产生同名产物。
