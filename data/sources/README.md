# 必要来源

`rules/` 保存共用规则仍需使用的少量官方规则卡和用户确认原文，`rules/sources.json` 保存来源说明与哈希。最终对局的来源定位在每局 game.json.source.media 中。

`weibo_checkpoint.json` 仅保存已完成采集日期区间及帖子 ID/日期，避免历史原件删除后整季重采；它不替代当前批次分析所需的微博原件。

[`bilibili_subtitles/`](bilibili_subtitles/README.md) 保存 S15–S20 分赛季采集计划的入口、字幕资源清单、进度与必要证据。计划位于 `data/indexes/S15_采集计划.json` 至 `S20_采集计划.json`，参考 S21 格式；未找到中文字幕的条目使用官方源，后续可转写。已保存字幕、有轨待全文、官方源待转写或复核分别记录，重复查询缓存已清理。
