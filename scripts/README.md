# 通用工具

统一入口是 `workflow.py status|plan|run --season <赛季>`：

| stage | 动作 |
| --- | --- |
| `collect` | 发现并采集新增官方媒体及微博窗口 |
| `process` | 为当前批次准备已有中文字幕或主模型转写、空候选及本地阅读资料 |
| `review` | 校验当前窗口已整理的候选，生成本批人工复核页 |
| `finalize` | 用 `--review-export` 和可选 `--note-revisions` 将人工确认结果写为最终 JSON |
| `export` | 从全部最终 JSON 生成本地网站静态数据 |
| `verify` | 只读校验最终数据及导出投影 |

`update_incremental.py`、`analyze_incremental.py`、`apply_incremental_review.py` 均接受赛季参数。实际版型差异由 `config` 表达。分析由当前窗口完成，工具不调用另一个模型。

采集复用 `collect_season.py`、`collect_bilibili_audio.py`、`collect_weibo*.py`；缺少可用中文文字时才用 `transcribe_funasr.py`。`capture_bilibili_frame.py` 根据已确定的时点取画面。身份、阵营、票型和特殊结算的规则模块继续复用。历史赛季导入器、数据库写入与一次性审计工具已退役。

完整步骤和授权边界见[增量流程](../docs/08_增量更新流程.md)。
