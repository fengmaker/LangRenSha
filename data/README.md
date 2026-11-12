# 数据

- `games/<赛季>/<局目录>/game.json`：唯一正式结果。`rules_state` 保留最终存活、夜死和槽位状态；`bluffs` 保留决定、成功与人工/未知状态。不能把 null、unknown、未进入行动、未复核转换为零或失败。
- `sources/rules/`：共用规则仍需使用的少量规则卡与用户确认，以及来源索引。
- `sources/weibo_checkpoint.json`：已完成的官方微博采集日期区间和帖子 ID/日期，删除历史原件后避免整季重采。
- `indexes/*_采集计划.json`：官方媒体来源基线。

`raw`、`transcripts`、`extractions`、`reports`、`manual_review` 等只供当前增量批次使用，均忽略 Git。已完成对局不长期保存截图、全文转写、推断、复核页面、反馈或验收回执。若修订历史局，从最终数据中的官方链接重新定位来源。
