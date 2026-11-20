# 网站语义回归

覆盖个人指标、胜负与阵营、悍跳和未知分母、版型特殊结算、展示时间线、稳定人物与照片，以及直接静态导出。测试使用最终 game.json 或必要的小型合成 fixture；不需要数据库、旧转写和历史复核资料。

在项目根目录运行 `python -m pytest website/tests -q`。在 `website/web` 运行 `npm test`，统一执行浏览器数据读取、查询、时间线、个人页和共用排名的离线检查。页面改动再运行 `npm run typecheck`。本地预览用 `website/run.py`，明确要求构建或上线时才调用 `static_publish` 的成品流程。
