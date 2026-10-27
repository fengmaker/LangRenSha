# 脚本职责与统一入口

日常先用`workflow.py status/plan/run --season ...`，不需要从一百多个内部模块中猜入口。历史赛季按[操作手册](../docs/15_赛季数据全流程操作手册.md)逐步执行，已核实成果直接复用；按文件定位实现时查[职责索引](INDEX.md)。

| 区块 | 对外入口 | 内部实现／适用范围 |
| --- | --- | --- |
| 阶段调度 | `workflow.py` | 六个自动化阶段处理命令顺序、执行环境和全保留季发布；不代替微博或逐局判断，不生成任务单 |
| 赛季注册 | `season_config.py` | 读取`config/seasons.json`；各采集／转写CLI与网站共用 |
| B站媒体 | `workflow ... --stage collect` | `collect_season`、`collect_official_audio`、`collect_bilibili_audio`；`auth_support/login_session`处理本机登录复用 |
| 微博与姓名照片 | 独立按[微博流程](../docs/06_微博排班采集.md)执行 | `collect_weibo_archive`、`audit_weibo_archive`、`export_weibo_schedule`；新季需适配索引／名牌识读／确认导出；`audit_weibo_identity_mapping`仅复验现有S22/S23批次一致性 |
| 字幕与全文 | `workflow ... --stage transcribe` | `audit_season`、`transcribe_review_queue`、`transcribe_funasr`、`register_season_transcripts`；独立ASR环境和检查点 |
| 画面与片段复听 | 按缺口补证据 | `capture_season_speech_frames`、`capture_bilibili_frame`、`review_asr_clip`、复盘窗口规划；OCR只是候选 |
| 推导与复核 | 先读证据，再`--stage review` | `recap_parser`、`game_flow/voting_*`及各季review/audit；S22/S23实际规则差异保留适配，不冒充任意季通用引擎 |
| 正式记录 | `workflow ... --stage import` | `formal_entry/game_records`、S22修订批处理、S23固定快照导入；来源与事务保护保留 |
| S21 身份专项 | `import_s21_identities.py` | 只验证座位、姓名、物理底牌；`--import-db`写入已核提取层，`reviewed_identity_seats`可查，不生成完整正式对局 |
| 网站发布／验收 | `workflow ... --stage publish/verify` | 网站模块构建完整release、逐季悍跳同步；`website/check_publication.py`动态核对源/API/页面 |
| 备份与清理 | `backup_database.py`、`cleanup_data.py` | 全库＋各季源基线；清理器先预览，保护DB引用、当前manifest和证据，不删原媒体 |
| 环境与资料登记 | `local_postgres.py`、`database.py` | 本机PostgreSQL和原始资料schema；早期revision命令不等于网站发布 |
| 专项研究／导出 | 仅有对应需求时 | 本地模型横评、离线复核包、人名工作簿等不进入日常主线 |

`templates/`保存生成复核网页的HTML/JS；不直接手改生成的离线HTML当作源实现。

已删除：根目录一次性`special_report.py/.txt`、旧Whisper和独立Qwen运行器、旧候选样例生成／导入器、重复S23备份入口。其有用结论和被引用证据保留；不要从临时文件恢复旧管线。

原始哈希、BV/CID、事务和删除范围检查是实际数据保护；已取消固定25条队列、已弃运行器专测及模板字面量断言。新增测试只验证真实来源、跨季隔离、状态/阶段合同或数据语义。
