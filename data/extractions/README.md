# 媒体提取与画面证据

本目录保存从 `raw/` 媒体解码或截取出的画面、帧序列和结构化提取记录，按赛季及提取任务组织。

- `.png` / `.jpg` 是抽取的帧或裁剪图；`.json` 记录来源、时间点、处理结果或复核定位。
- 日期清单和逐局目录用于把提取结果对应回原始 BVID、局次和画面时间。
- 需要与转写、原视频和正式档案交叉复核时，保留被报告或数据库引用的画面及旁证。
- 这些是证据衍生文件，不等同于原始媒体；不要整目录当缓存删除。
- 全流程入口为 [scripts/workflow.py](../../scripts/workflow.py)：先 `status --season S22`，再按注册赛季预览 `plan`。
- 原件保存在 [raw](../raw/README.md)，转写续跑材料在 [transcripts](../transcripts/README.md)。

S21 座位、姓名、真实底牌专项使用 `S21/game_reviews/{BVID}/identity.reviewed.json`。
它从已实际查看的 `visual_review.json` 派生，应用独立的
`S21/identity_primary_corrections.json`，保留旧值、原图 SHA 和定位。
数据库保存为 `extraction_runs.method='visual_identity_only_v1'` 的已核提取，
通过 `jcms.reviewed_identity_seats` 查询最新版本。这里的“已核”指助手目视核实，
不表示用户逐字段确认。它只含座位、姓名、物理底牌，不创建完整正式对局，
也不恢复日夜、悍跳、阵营、胜负或网站发布。
进度见 [S21专项报告](../reports/S21_座位姓名身份核实进度.json)，
验证／重放入口为 `python scripts/import_s21_identities.py`；
追加 `--import-db` 才写入数据库，重复相同文件不重复生成记录。
