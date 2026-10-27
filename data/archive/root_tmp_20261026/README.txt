根目录临时文件归档（2026-10-26）

来源：D:\langrensha 根目录下 .tmp 开头的10个文件。
整理方式：原样移动，文件名、内容及原修改时间保留；逐文件SHA256已核对。
manifest.json 记录原位置、归档位置、字节数、原修改时间、用途和SHA256。

scripts/：9个S23复核辅助脚本，覆盖转写查找、发言切分、F分片早期写入和修正。
reports/：1份S23早期诊断输出 .tmp_mismatches.txt，原文件含乱码，按原始字节保留。

这些文件用于追溯此前复核过程。早期写入脚本中的部分侧栏归属和起跳判断，
已由主审在正式复核分片中更正；归档脚本还保留原来基于根目录的路径假设。

当前结果与维护入口：
- data/extractions/S23/bluff_review/parts/audit_f.json：F分片最终复核记录。
- data/extractions/S23/bluff_review/primary_continue.py：主审转写与证据辅助工具。
- scripts/build_s23_bluff_publication.py：构建和校验S23悍跳公开数据。
- scripts/import_bluff_feedback.py：校验和导入用户反馈。
- data/reports/S23_悍跳本次交付_20261026.json：最终交付及发布记录。

以上路径均以 D:\langrensha 为根目录。
