# 脚本职责与统一入口

采集、人物身份、日夜票型、悍跳、写库、复核、发布与验收统一按[全流程](../docs/01_赛季数据全流程.md)执行；阶段命令用`workflow.py status/plan/run --season ...`，定位实现时查[职责索引](INDEX.md)。

持续比赛后的日常新增资料直接使用[增量更新流程](../docs/08_增量更新流程.md)中的`update_incremental.py`、`analyze_incremental.py`和`apply_incremental_review.py`，不调用旧S23固定75局整链追加新局。

| 区块 | 对外入口 | 内部实现／适用范围 |
| --- | --- | --- |
| 阶段调度 | `workflow.py` | 六个自动化阶段处理命令顺序、执行环境和全保留季发布；不代替微博或逐局判断，不生成任务单 |
| 每日增量采集 | `update_incremental.py --season S23` | 在线比较正赛/决赛周合集，按本地微博窗口续到今天；确认前不请求微博，确认后用官网帖子列表采集。`--check-only`只查差距，`--yes`明确同意采集 |
| 新局资料准备 | `analyze_incremental.py --season S23 --prepare-only` | 缺文字才ASR；随后由当前窗口用户所选模型阅读微博、文字与截图，校验候选并生成复核页；旧默认入口含模型CLI，不再调用 |
| 标准逐局复核页 | `game_review_page.py --season S23 [--bvid ...] [--output ...]` | 使用已准备的候选和`review_display.json`；按[09](../docs/09_复核页面生成规范.md)生成身份截图、座位身份、单行悍跳人/成功选择、共用流程、复盘文字及意见填写区，输出离线v2意见页 |
| 日夜与票型呈现 | `game_timeline.build_game_timeline` | 复核页与网站共用阶段、事件/票轮顺序及角色触发；常规角色与特殊版型按[10](../docs/10_对局信息呈现规范.md)生成展示序列 |
| 应用新局人工结果 | 当前窗口接收复核导出JSON | 当前模型解释备注并生成预览；授权后复用`apply_incremental_review.py`的校验、备份、事务及发布函数。非空备注的旧模型CLI分支不再调用，详见[增量流程](../docs/08_增量更新流程.md) |
| 赛季注册 | `season_config.py` | 读取`config/seasons.json`；各采集／转写CLI与网站共用 |
| B站原件采集 | `collect_season.py plan/run --season ...`；也可`workflow ... --stage collect` | `collect_bilibili_audio`先取中文字幕，无可访问中文轨才取音频；只写本机文件，见[第一步](../docs/01_赛季数据全流程.md#第一步采集原始资料) |
| 微博原件采集 | `collect_weibo_archive.py --since ... --until ...` | 从官网作者帖子列表归档指定日期窗口，需有效weibo.com登录态；不使用移动端getIndex，长文/详情/配图沿用已有原件机制。`audit_weibo_archive`独立复验，后续排班见[微博流程](../docs/01_赛季数据全流程.md#确定当天出场嘉宾) |
| 按需全文与复听 | `transcribe_funasr.py --no-speakers`、`extract_audio_window.py` | 缺文字才转写，疑点才复听；独立ASR环境与检查点保留。旧`transcribe_review_queue`仍需审计CSV，调度不再自动入库 |
| 画面与片段复听 | 按缺口补证据 | `capture_season_speech_frames`、`capture_bilibili_frame`、`review_asr_clip`、复盘窗口规划；OCR只是候选 |
| 日夜与票型 | 按[第三步](../docs/01_赛季数据全流程.md#第三步核实日夜流程与票型)核具体证据 | `s21_phase_review`、`audit_s21_phases`与各季票型实现按输入契约复用，未知和弃票分开，不自动入库 |
| 悍跳与成功率 | 按[第四步](../docs/01_赛季数据全流程.md#第四步识别悍跳与计算成功率)由用户逐局填写 | `build_manual_bluff_review.py --season S21\|S23 [--check]`生成按日期分组的空白表（默认S21），前置12席名单及截图，包含混血儿；不自动识别或预填结论。历史S22/S23构建器保留既有输入 |
| S23人工悍跳结果应用 | `build_manual_bluff_publication.py --manual <JSON> [--prepare]`；既有 `website.api.publish_bluffs --season S23` | 前者默认只核对并比较，prepare归档原件和写本机资产／报告；后者经检查后事务写入悍跳版本表。人工成功结果优先，用户选中的额外席位完整纳入，空白局保留原值 |
| 局部事实复核 | 按[第六步](../docs/01_赛季数据全流程.md#第六步局部复核与意见核对)直接只读目标证据 | 只核点名的局、字段和区域，具体矛盾才查直接依赖；不会自动生成整季报告或应用意见 |
| S23单局机械检查 | `check_s23_game.py --bvid ... [--checks structure rules evidence] [--field ...]`；也可 `workflow --stage review --bvid ...` | 审计、候选生成和导入准备共用`s23_effective_game.py`；输出正式值差异、证据与直接影响。`--field`限制差异/原文旁证，结构通过不代表事实已核 |
| 整季结构校验/生成 | `workflow --stage review --full-season` | 保留S22/S23原review/audit链；会写整季报告，S23还重建候选/页面；不能与`--bvid`混用，不代表AI事实复核 |
| 数据库写入 | 按[第五步](../docs/01_赛季数据全流程.md#第五步核对后写入数据库)选择范围；正式适配用`workflow ... --stage import` | S21正式适配复用已核专项记录；原件登记与通用对局支持纯字幕；S23加BV时只生成/准备该局并单遍导入变更，完整范围保留双遍幂等验收；S22单局import-edits不自动导完整voting |
| S21 正式对局 | `import_s21_formal.py --check/--prepare/--import-db [--bvid ...]` | 从已核身份、主审批准的日夜spec及原文构建正式JSON；局、票型与拍刀共享事务，原始细节保留旁证，未知不补造 |
| S21 身份专项 | `import_s21_identities.py` | 只验证座位、姓名、物理底牌；`--import-db`写入已核提取层，`reviewed_identity_seats`可查，不生成完整正式对局 |
| 网站发布／验收 | `workflow ... --stage publish/verify` | 网站模块构建完整release、逐季悍跳同步；`website/check_publication.py`动态核对源/API/页面 |
| 备份与清理 | `backup_database.py`、`cleanup_data.py` | 全库＋各季源基线；清理器先预览，保护DB引用、当前manifest和证据，不删原媒体 |
| 环境与资料登记 | `local_postgres.py`、`database.py`、`collect_official_audio.py`、`register_season_transcripts.py` | 显式原始音频／文字登记与本机PostgreSQL；采集和转写不自动触发，早期revision命令不等于网站发布 |
| 专项研究／导出 | 仅有对应需求时 | 本地模型横评、离线复核包、人名工作簿等不进入日常主线 |

`templates/`保存生成复核网页的HTML/JS；不直接手改生成的离线HTML当作源实现。

已删除：根目录一次性`special_report.py/.txt`、旧Whisper和独立Qwen运行器、旧候选样例生成／导入器、重复S23备份入口。其有用结论和被引用证据保留；不要从临时文件恢复旧管线。

原始哈希、BV/CID、事务和删除范围检查是实际数据保护；已取消固定25条队列、已弃运行器专测及模板字面量断言。新增测试只验证真实来源、跨季隔离、状态/阶段合同或数据语义。
