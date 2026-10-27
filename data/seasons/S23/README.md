# S23 官方音频、字幕与发言截图

2026-10-26，按官方《昆仑归墟》合集（8992596，UID 19106800）最新实际返回的87条媒体归档：12条表演赛、75条正赛，标题日期覆盖2026-09-01至2026-10-16。当前合集仍为87条，与2026-10-20候选目录数量一致；不代表合集外、未公开或删除的录像均已找到。

正赛数据推导请打开 [S23逐局推导与复核](../../exports/S23_逐局推导与复核.html)，范围仅75局正赛，表演赛已排除；可查看底牌、夜间事件、警徽票、放逐票、悍跳、拍刀及复核意见。75局已于2026-10-26正式入库并与S22的148局共同发布到本机网站；候选和原始旁证继续保留。详见[数据复核说明](../../../docs/14_S23逐局推导与复核.md)和[全流程操作手册](../../../docs/15_赛季数据全流程操作手册.md)。

原始资料可打开 [音频字幕截图目录](S23_音频字幕截图复核.html) 或 [CSV目录](S23_音频字幕截图复核目录.csv)。每局集中链接原始音频、带时间戳全文、SRT和原尺寸截图。

## 已完成的资料

- 87条独立音轨，合计115.47小时、5,245,208,604字节（约5.25 GB / 4.885 GiB）。全部通过官方来源、BV/CID/P、文件SHA256、时长、无视频轨、起始解码及数据库登记检查。
- 84份平台中文字幕，204,780条原始字幕；时间覆盖筛查未发现明显截短信号。平台原始JSON、SRT和阅读TXT均保留。
- 另外3条音频已用本机CUDA Paraformer完成整段转写，保留赛前、对局、赛后内容，输出JSON、SRT、阅读TXT以及分块检查点，合计约4.41小时。见 [全文补转写目录](S23_全文补转写目录.csv)。
- 87张1920×1080发言截图，逐张目视检查座位姓名图层，保留可见的警徽票与放逐票标记。图例为红底数字代表警徽票、绿底数字代表放逐票；某局未显示某类票型时不据此补造投票。
- 87个来源、87个选用转写版本、213,098个文字片段已登记现有PostgreSQL资料表。来源按BVID:CID绑定，重复登记同一文件不增加重复转写。一个平台字幕的空白条目未写入文字片段表，原始JSON保持不变，派生JSON保存省略位置。

## 截图定位与核对边界

截图先按靠后的明确座位发言指令定位，再目视检查。遇到图层消失、分屏、夜间全景或空椅子时，另留附近或之前玩家发言的清晰画面，原先的帧仍保留。每局 `data/extractions/S23/speech_frames/{BVID}/capture.json` 记录BV/CID、时点、截图及文字来源SHA256、发言原句、取帧说明和数据库文件ID。

优先靠后的发言是为了尽量覆盖最后游戏日。当前尚未逐局重建完整日序，因此不把“最晚匹配到发言指令”当作“末日已确认”，收据中的 `last_game_day_verified` 仍保留为false。后续提取票型时应结合画面游戏日、原文播报及各轮投票分别核对。

音频整理副本使用硬链接，媒体不重复占一份空间。原始字幕和本地模型稿均未经逐字人工校对，不能直接视作已确认的身份、票型或积分事实；媒体采集阶段不创建正式对局事实。后续逐局推导、用户确认、正式导入和网站发布分别保留记录；当前正式库已导入S23，资料未公开字段仍保持未知。

## 续跑命令

在项目根目录执行；采集复用现有本机Cookie，模型仅使用已有本地权重。

```powershell
.\.venv\Scripts\python.exe scripts/local_postgres.py start
.\.venv\Scripts\python.exe scripts/collect_season.py status --season S23
# 需要更新官方目录时先刷新冻结计划，再下载新增项
.\.venv\Scripts\python.exe scripts/collect_season.py plan --season S23 --auth cookies --cookies-file .secrets/bilibili.cookies.txt
.\.venv\Scripts\python.exe scripts/collect_season.py run --season S23 --auth cookies --cookies-file .secrets/bilibili.cookies.txt --workers 2
.\.venv\Scripts\python.exe scripts/audit_season.py --season S23
.\.venv-funasr39\Scripts\python.exe scripts/transcribe_review_queue.py run --season S23
.\.venv\Scripts\python.exe scripts/register_season_transcripts.py --season S23
.\.venv\Scripts\python.exe scripts/capture_season_speech_frames.py --season S23 --auth cookies --cookies-file .secrets/bilibili.cookies.txt
# 新增截图需要目视核对；完成后重建复核目录与验收
.\.venv\Scripts\python.exe scripts/build_season_media_review.py --season S23
```

续跑新增截图不会自动得到目视核对标记。S22默认命令与历史资料目录保持独立，S23计划、日志、进度和导出均使用独立赛季路径。
