# 狼人杀 ASR 三模型实测

本页为冻结的测试记录。之后已按用户要求移除独立 Qwen/Whisper 权重和专用环境，保留 Paraformer 与 Nano；结果、对照音频与阅读页面仍保留。当前运行入口见 [本地资源与清理](08_本地资源与清理.md)。

2026-10-22 已完成 SeACo Paraformer、Qwen3-ASR-0.6B、Fun-ASR-Nano-2512 的本地对照：三场对局、13 段共 5 分 28.10 秒，分别运行无提示和共同 40 词提示，共 78 次推理。

文字审阅后的工程建议是：复盘优先 Nano + 精简提示；批量初稿继续 Paraformer；本轮 Qwen3-ASR-0.6B 未显示替换优势。没有人工逐字真值，故未报告识别准确率，也未更换当前默认转写模型。

- [完整结论、具体原文差异、耗时与复跑方式](../outputs/asr_model_benchmark_20261022/report.md)
- [可切换条件、播放原声的三列对照页面](../outputs/asr_model_benchmark_20261022/comparison.html)
- [全部模型结果与运行配置](../outputs/asr_model_benchmark_20261022/summary.json)
- [固定音频清单与哈希](../outputs/asr_model_benchmark_20261022/corpus.json)

测试用 40 词包独立保存，未替换现有 343 词配置。具体身份、数字、技能仍需回听核验；模型共识和术语命中均不能代替原声真值。
