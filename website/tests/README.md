# 网站语义回归

覆盖不可变快照／原子发布、多赛季保留、个人指标、混血阵营、悍跳与用户反馈，以及S23具体终局和技能结算。纯统计测试不读媒体，数据库测试使用自己的临时schema。执行python -m pytest website/tests -q；真实本机API与页面另用website/check_publication.py。

前端票卡与时间线组件的离线React SSR回归：`node website/tests/check_web_semantics.cjs website/web/node_modules website/web/src`。

静态列表排序／筛选和排名并列、两种场次门槛叠加：`node website/tests/check_static_queries.cjs website/web/node_modules website/web/src`。静态快照完整性、版本切换、图片缺失与失败保留在对应 `test_static_*.py`；真实API、HTML和子路径浏览器流程由 `website/static_publish/check_static.py` 一并验收。

增量输入指纹、跨发布复用和局部失效分别见 `test_export_inputs.py`、`test_incremental_export.py`、`test_incremental_acceptance.py`；自动同步的路径保护、差异文件写入、提交范围和部署失败回执见 `test_pages_sync.py`。临时目录受限时，可给 pytest 添加 `--basetemp=tmp/pytest-local`，使用本工作区内的专用目录。

网页程序复用、新增／删除详情地址及源码变化触发重建由 `test_static_build.py` 覆盖；小范围浏览器路由选择和 `--skip-browser-check` 保留结构／API 检查由静态验收测试覆盖。日常发布默认不逐条遍历全站浏览器路由，回执记录实际检查范围及浏览器是否跳过。

