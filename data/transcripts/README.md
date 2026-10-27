# 转写记录与续跑材料

本目录保存按视频或赛季整理的转写结果、字幕和 ASR 分段产物。

- `.json` 保存带时间戳的转写段、来源信息和处理状态；`.srt` 是便于阅读和播放器核对的字幕。
- 名称含 `raw` 的响应及 `chunk` 分段是续跑资产，用于恢复失败或未完成的转写任务，不是临时缓存。
- 不要删除 `raw` / `chunk` 文件，也不要仅凭转写文本改写原始事实；它们需要回到画面与正式记录复核。
- 统一入口是 [scripts/workflow.py](../../scripts/workflow.py)：`status --season S22` 查看进度，`plan --season S22 --stage transcribe` 预览队列。
- 执行 ASR 阶段由流程调用独立 `.venv-funasr39` 环境；该环境与 Python 3.12 采集环境分开。
- 原始音频与字幕在 [raw](../raw/README.md)，截图材料在 [extractions](../extractions/README.md)，正式档案在 [games](../games/README.md)。
