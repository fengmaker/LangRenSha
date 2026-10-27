# 网站语义回归

覆盖不可变快照／原子发布、多赛季保留、个人指标、混血阵营、悍跳与用户反馈，以及S23具体终局和技能结算。纯统计测试不读媒体，数据库测试使用自己的临时schema。执行python -m pytest website/tests -q；真实本机API与页面另用website/check_publication.py。

前端票卡与时间线组件的离线React SSR回归：`node website/tests/check_web_semantics.cjs website/web/node_modules website/web/src`。

