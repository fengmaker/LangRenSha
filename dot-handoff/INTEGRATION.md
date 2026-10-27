# 部署与Actions补丁接续记录

日期：2026-10-27（北京时间）。基线 `89cf2ab3db1b32117dcefbda581fcb36c1828240`。

| 改动 | 本地及远端提交 |
| --- | --- |
| S22/S23部署配置 | `3bea6eb4cf28b8698e17393645247185e16656b1` |
| 独立Actions全链路验收 | `e23350df097dee035cb9a6231e796189e09054d5` |

分支：`ci/full-acceptance`，已推送至 `origin/ci/full-acceptance`。接收机器的git am生成了新的提交号，原交付提交号仍保留在两份原件中。未合并main，未部署正式站点。

本地：156项纯/mock测试、223局源预检、前端typecheck、Python语法、YAML结构及diff空白检查通过。6项数据库测试未在本地执行。

[Actions真实验收](https://github.com/fengmaker/LangRenSha/actions/runs/40483537880)：已结束：success。具体证据见接续记录。

验收要求包括一次性PostgreSQL发布、两季悍跳绑定、全部网站测试零跳过、只读权限、真实API及桌面/手机viewport页面。只有绿色job及对应result/acceptance证据均通过才确认全链路成功；不会把原交付的历史测试结果当作Actions结果。

## 已核对的真实验收证据

- `result.json` 为 passed：162项网站测试实际执行、零跳过，223局数据，数据库只读权限通过，36页浏览器检查通过。
- `acceptance.json` 为 passed：S22 148局、S23 75局；223局详情逐一与源匹配；两季悍跳绑定正确；118份照片资产通过校验；两季在两种视口均解码照片。
- 产物共36张定尺寸页面截图，桌面1440×1000、手机视口390×844，各18页。已检查截图总览，无明显空白/错误页面；这不是物理手机或其他浏览器内核验收。
- 下载ZIP的SHA256与GitHub artifact digest一致：`a125b3a26975e1c1b2f1bf7c3f6c4138f130a64d6678b065a1d1939faca841d7`。

核验副本：[result.json](ci-verification/result.json)、[acceptance.json](ci-verification/acceptance.json)、[截图总览](ci-verification/screenshot-index.jpg)、[artifact元数据](ci-verification/artifact.json)。完整下载与解包日志留存在本地 `website/artifacts/ci-run-40483537880.zip` 和同名目录，未提交至Git。

本次在一次性GitHub runner上完成PostgreSQL、真实API、前端生产构建及浏览器验收。部署用API/web镜像构建、完整Compose启动、正式环境发布、TLS和备份恢复演练仍未执行。
