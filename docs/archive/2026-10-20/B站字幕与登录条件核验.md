# B站字幕与登录条件核验

> 历史参考：本文件保留此前方案与试验过程。当前执行范围以 [项目入口](../../../README.md) 和 [三步路线](../../01_项目路线.md) 为准；当前只推进第一步原始媒体采集。旧文中的“下一步”不作为当前任务。

核验日期：2026-10-20。依据 yt-dlp 官方 `master` 分支源码/README，以及 Bilibili 官方 ESG 报告；没有登录账号、读取 Cookie 或下载媒体。此处是对代码路径的核验，不是对所有视频逐条探测。

后续实测：主代理对 `BV1tj8p6REqy`（CID `41072527914`）与 `BV1z6tG6rEfw`（CID `41501459682`）执行匿名 `/x/player/v2` 请求，均返回 HTTP 200、业务状态 0、`login_mid=0`、`need_login_subtitle=true`、空字幕列表。应正常登录后再探测，不能据此声称没有字幕，也不能保证登录后一定有 AI/人工字幕。记录见 `data/diagnostics/subtitle_public_probe.json`。

## 结论

- **可以直接取得平台公开给播放器的字幕轨。** yt-dlp 的 Bilibili extractor 请求 `/x/player/wbi/v2`，读取 `data.subtitle.subtitles` 中有 `subtitle_url` 和 `lan` 的条目，下载字幕 JSON 并转换为 SRT。它也读取 `need_login_subtitle`；该字段为真时会明确提示“字幕仅登录后可用”。源码测试还标出一条有 CC 字幕、但字幕需登录的视频。因此登录要求按视频/字幕授权而异，不能概括成“字幕都要登录”或“字幕都公开”。[extractor 源码](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py)
- **人工字幕与 AI 字幕：** extractor 不依据 `type` 等字段判别人工/AI来源，也没有单独的 AI 字幕接口或 OCR 转录流程。若某轨被该 API 返回并带可用 URL，代码会按普通平台字幕轨处理；仅凭播放器有 AI 字幕按钮，不能推出该内容存在可公开下载的字幕文件。Bilibili 官方报告确实提到过无障碍直播间的 AI 字幕，说明该产品能力存在，但不说明普通视频的字幕 API 覆盖范围或登录条件。[Bilibili 2023 ESG 报告](https://ir.bilibili.com/media/ftcjhpj4/bps23090002_bilibili-2023esg_sc_c4856.pdf)
- **自动字幕选项不等于请求 B站生成 AI 字幕。** yt-dlp README 将 `--write-subs` 和 `--write-auto-subs` 作为通用下载选项说明；当前 Bilibili extractor 返回的是 `subtitles`，源码没有 `automatic_captions` 字段。不能把 `--write-auto-subs` 解释成它会为无轨视频现场语音识别。[yt-dlp README：字幕选项](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#subtitle-options)
- **烧录字幕**已经成为视频画面像素的一部分，不是独立字幕轨；当前脚本只请求播放器字幕 JSON，且媒体部分只取独立音轨，不读取视频帧或做 OCR，所以无法提取烧录字幕。
- **AI 总结**是视频理解/摘要类内容，不是逐句带时间轴的字幕轨。Bilibili ESG 报告另提到 AI 视频小助手用于内容总结和高能时刻提醒；这不是上述字幕 extractor 读取的字段。[Bilibili 2023 ESG 报告](https://ir.bilibili.com/media/ftcjhpj4/bps23090002_bilibili-2023esg_sc_c4856.pdf)
- **弹幕**是按时间显示的观众评论，不等同于字幕。yt-dlp 为其单独提供 `danmaku` XML 项；当前项目脚本没有采集弹幕。[extractor 源码](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py)

## 登录条件与边界

当前可直接从 yt-dlp 源码确认：当 `need_login_subtitle` 为真时，代码提示需登录；源码测试也包含“视频有字幕，但字幕需要登录”的实例。代码同时会照常遍历 API 实际返回的字幕轨，所以公开可见轨并不一律要求登录。README 提供 `--cookies FILE`、`--cookies-from-browser` 等通用 Cookie 选项，但这只是 yt-dlp 可加载登录态的能力，不证明每一轨登录后都能取得，也不证明 B站每种登录门槛、会员或地区条件。[README：Cookie 选项](https://github.com/yt-dlp/yt-dlp/blob/master/README.md#filesystem-options)

本次未找到能把普通视频、AI字幕、地区/会员权限统一说明的 Bilibili 官方帮助文档；以上登录结论限于 yt-dlp 当前实现明确识别的字段和测试样例。公开视频中无轨可能表示没有对 API 暴露的独立字幕、当前请求未获授权、轨道暂不可用或接口行为变化；不能单凭空列表判断视频画面中无字幕，也不能证明不存在 AI 字幕。

## 对现有脚本的核对与建议

`scripts/collect_bilibili_audio.py` 默认不读 Cookie，现已支持显式 `--auth cookies --cookies-file PATH`；使用 `/x/player/v2`，检查 `subtitle.subtitles` 并保存可见轨 JSON。登录保护且无可见轨时记为 `login_required`，保留原始登录提示及轨道语言、ID、AI 标记；真实匿名 API 复测两例均为 `login_required`。API 失败记为 `unavailable_in_this_request`。yt-dlp 当前字幕实现使用 `/x/player/wbi/v2`，项目仍未接入该 WBI 请求路径，真实账号登录后的字幕可用性尚未实测。登录命令见[数据库与单视频完整流程](数据库与单视频完整流程.md)。

建议 manifest 分开保留：

- `subtitle_request`: endpoint、匿名/已认证/未知（不要读取浏览器 Cookie；若以后显式提供凭据，应只记录认证模式，不落盘凭据）；
- `subtitle_access`: 原始 `need_login_subtitle`（`true/false/null`）、API 状态、`tracks_reported`、`tracks_downloaded`，并区分 `login_required`、`none_reported`、`request_failed`、`tracks_visible`；
- 每轨保存 `lan`、`lan_doc`、`id`、原始 `type`、`is_lock`、下载状态及平台提供的原始 JSON。来源可标为“平台字幕轨 / 来源类型未判定”，不要仅凭字段猜成人工或 AI；
- 如需覆盖其他来源，另记 `burned_in_ocr`、`danmaku`、`ai_summary` 的独立采集状态。当前能力未实现时标为 `not_attempted`，避免与字幕轨状态合并。

接口和权限可能随 B站调整；以上反映访问日可见的 yt-dlp 源码，未对所有视频、账号或客户端功能作保证。
