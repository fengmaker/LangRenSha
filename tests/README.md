# Python 测试

本目录保存项目 Python 单元测试、集成测试和小型测试夹具。

- `test_*.py` 是 pytest 用例；共享帮助代码或少量模拟数据可放在同目录。
- 根目录用例覆盖数据库记录、采集、转写辅助、规则和证据结构；网站 API 用例在 `website/tests/`。
- 测试使用当前 Python 3.12 清单：[requirements/test.txt](../requirements/test.txt)。
- 从项目根运行完整 Python 用例：`python -m pytest tests -q`。
- 网站 API 测试：`python -m pytest website/tests -q`；运行前需要其配置的服务或数据库条件。
- 本机数据库集成测试前先运行 `.\.venv\Scripts\python.exe scripts/local_postgres.py start`；导入测试使用隔离 schema，API 测试读取已有发布。数据库未启动会造成连接错误或跳过，不能当作验证通过。
- 使用 [scripts/workflow.py](../scripts/workflow.py) 预览正式赛季阶段；不要用旧试验管线替代测试。
- 测试夹具不是业务原件；正式媒体和人工证据仍按 `data/` 下的职责目录保存。
