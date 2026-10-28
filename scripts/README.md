# 脚本职责与统一入口

采集、人物身份、日夜票型、悍跳与成功率、数据库写入和局部复核按[统一流程](../docs/02_采集与座位姓名身份核实.md)执行；后续阶段用`workflow.py status/plan/run --season ...`。总体顺序见[操作手册](../docs/15_赛季数据全流程操作手册.md)，定位实现时查[职责索引](INDEX.md)。

| 区块 | 对外入口 | 内部实现／适用范围 |
| --- | --- | --- |
| 阶段调度 | `workflow.py` | 六个自动化阶段处理命令顺序、执行环境和全保留季发布；不代替微博或逐局判断，不生成任务单 |
| 赛季注册 | `season_config.py` | 读取`config/seasons.json`；各采集／转写CLI与网站共用 |
| B站原件采集 | `collect_season.py plan/run --season ...`；也可`workflow ... --stage collect` | `collect_bilibili_audio`先取中文字幕，无可访问中文轨才取音频；只写本机文件，见[第一步](../docs/02_采集与座位姓名身份核实.md#第一步采集原始资料) |
| 微博原件采集 | `collect_weibo_archive.py --since ... --until ...` | 采官方账号日期窗口内全部可见发布；`audit_weibo_archive`为独立原件复验，排班导出与姓名照片识读属于后续[微博流程](../docs/02_采集与座位姓名身份核实.md#确定当天出场嘉宾) |
| 按需全文与复听 | `transcribe_funasr.py --no-speakers`、`extract_audio_window.py` | 缺文字才转写，疑点才复听；独立ASR环境与检查点保留。旧`transcribe_review_queue`仍需审计CSV，调度不再自动入库 |
| 画面与片段复听 | 按缺口补证据 | `capture_season_speech_frames`、`capture_bilibili_frame`、`review_asr_clip`、复盘窗口规划；OCR只是候选 |
| 日夜与票型 | 按[第三步](../docs/02_采集与座位姓名身份核实.md#第三步核实日夜流程与票型)核具体证据 | `s21_phase_review`、`audit_s21_phases`与各季票型实现按输入契约复用，未知和弃票分开，不自动入库 |
| 悍跳与成功率 | 按[第四步](../docs/02_采集与座位姓名身份核实.md#第四步识别悍跳与计算成功率)逐局核实 | `website/api/bluffs.py`复用判断与汇总；S22/S23构建器的`--check`读取各季既有复核输入，保留未知，不自动发布 |
| 局部事实复核 | 按[第六步](../docs/02_采集与座位姓名身份核实.md#第六步局部复核与意见核对)直接只读目标证据 | 只核点名的局、字段和区域，具体矛盾才查直接依赖；不会自动生成整季报告或应用意见 |
| 整季结构校验/生成 | `workflow --stage review --full-season` | 保留S22/S23原review/audit链；会写整季报告，S23还重建候选/页面；不能与`--bvid`混用，不代表AI事实复核 |
| 数据库写入 | 按[第五步](../docs/02_采集与座位姓名身份核实.md#第五步核对后写入数据库)选择范围；正式适配用`workflow ... --stage import` | S21正式适配复用已核专项记录；原件登记与通用对局支持纯字幕；S23备份→prepare→事务导入；S22单局import-edits不自动导完整voting |
| S21 正式对局 | `import_s21_formal.py --check/--prepare/--import-db [--bvid ...]` | 从已核身份、主审批准的日夜spec及原文构建正式JSON；局、票型与拍刀共享事务，原始细节保留旁证，未知不补造 |
| S21 身份专项 | `import_s21_identities.py` | 只验证座位、姓名、物理底牌；`--import-db`写入已核提取层，`reviewed_identity_seats`可查，不生成完整正式对局 |
| 网站发布／验收 | `workflow ... --stage publish/verify` | 网站模块构建完整release、逐季悍跳同步；`website/check_publication.py`动态核对源/API/页面 |
| 备份与清理 | `backup_database.py`、`cleanup_data.py` | 全库＋各季源基线；清理器先预览，保护DB引用、当前manifest和证据，不删原媒体 |
| 环境与资料登记 | `local_postgres.py`、`database.py`、`collect_official_audio.py`、`register_season_transcripts.py` | 显式原始音频／文字登记与本机PostgreSQL；采集和转写不自动触发，早期revision命令不等于网站发布 |
| 专项研究／导出 | 仅有对应需求时 | 本地模型横评、离线复核包、人名工作簿等不进入日常主线 |

`templates/`保存生成复核网页的HTML/JS；不直接手改生成的离线HTML当作源实现。

已删除：根目录一次性`special_report.py/.txt`、旧Whisper和独立Qwen运行器、旧候选样例生成／导入器、重复S23备份入口。其有用结论和被引用证据保留；不要从临时文件恢复旧管线。

原始哈希、BV/CID、事务和删除范围检查是实际数据保护；已取消固定25条队列、已弃运行器专测及模板字面量断言。新增测试只验证真实来源、跨季隔离、状态/阶段合同或数据语义。
