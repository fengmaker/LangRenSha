# Next.js前端

先读本目录[AGENTS规范](AGENTS.md)；涉及框架约定时读安装版Next本地指南。

- `src/app/`按路由组织页面及专属样式；`layout.tsx/globals.css/interface.css`控制全站结构与通用视觉。
- `src/components/`是跨页复用的导航、座位、事件、票型和榜单交互。
- `src/lib/static-browser.ts`封装浏览器静态 JSON 查询，`types.ts`保存前端响应类型，`format.ts`只负责显示格式。
- 图片使用 `public/media` 中清单允许的正式照片；本地启动器从稳定照片基线准备媒体。
- `node_modules/`是安装依赖，`.next/`是本地维护构建，`.static-build/`是公开静态构建的独立工作目录，均不编辑。

本目录执行 `npm ci` 安装依赖，使用 `npm test` 和 `npm run typecheck` 验证前端。从项目根通过 [run.py](../run.py) 启动本地预览，完整流程见[网站说明](../README.md)。

明确要求同步线上网站时，入口为项目根的 `website/static_publish/sync_pages.py`，见[静态发布说明](../static_publish/README.md)。静态构建复用同一份源码及已安装的依赖。

本地预览与公开静态站使用同一套展示组件。首页和默认积分榜从当前静态快照预渲染；切换榜单赛季或阶段时读取对应的摘要，打开指标样本时才加载完整榜单明细。榜单的赛季、阶段及排序记在 URL 中。显式静态构建用 `NEXT_PUBLIC_SITE_MODE=static` 开启 `output: export` 与 `trailingSlash`，`NEXT_PUBLIC_BASE_PATH` 指定子路径。

选手目录只读取卡片要展示的字段，并按需加载缩略图；个人档案先显示缩略图，原图就绪后替换。对局记录和选手目录按清单选择内容地址，浏览器可以复用已有缓存，页面显示清单记录的发布版本。

首次静态构建、前端输入或数据快照变化时执行 Next 编译和类型检查，确保首页、积分榜和按需加载的数据来自同一快照。编译为对局、选手和赛季详情各生成一个 `__static__` 模板，并将模板保存在 `.static-shells/`。构建器按本次快照清单生成实际地址。公开模式跨页链接使用带 basePath 的原生地址，查询参数变化通过浏览器 history 与 Next hooks 同步。

构建成品从根目录调用 `website/static_publish/build_static.py`，完成必要结构和代表页面检查。静态生成文件不纳入源码 Git。网站展示悍跳统计所需的最终次数与成功结果，不公开逐条复核证据、截图或反馈工具。

全站共用的 `SiteTraffic` 组件仅在 `https://fengmaker.github.io/langrensha-site/` 下的公开页面加载 Cloudflare Web Analytics，数据在 Cloudflare 后台查看。`spa: false` 让同页筛选更新 URL 时跳过额外的页面访问计数。详见 [Cloudflare Web Analytics 文档](https://developers.cloudflare.com/web-analytics/get-started/)。
