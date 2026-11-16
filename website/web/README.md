# Next.js前端

先读本目录[AGENTS规范](AGENTS.md)；涉及框架约定时读安装版Next本地指南。

- `src/app/`按路由组织页面及专属样式；`layout.tsx/globals.css/interface.css`控制全站结构与通用视觉。
- `src/components/`是跨页复用的导航、座位、事件、票型和榜单交互。
- `src/lib/api.ts`封装静态 JSON 查询，`types.ts`保存前端响应类型，`format.ts`只负责显示格式。
- 图片使用 `public/media` 中清单允许的正式照片；本地启动器从稳定照片基线准备媒体。
- `node_modules/`是安装依赖，`.next/`是本地维护构建，`.static-build/`是公开静态构建的独立工作目录，均不编辑。

本目录执行`npm ci`、`npm run typecheck`。从项目根通过[run.py](../run.py)启动本地预览；完整流程见[网站说明](../README.md)。

明确要求同步线上网站时，入口为项目根的 `website/static_publish/sync_pages.py`，见[静态发布说明](../static_publish/README.md)。静态构建复用同一份源码及已安装的依赖。

本地预览与公开静态站使用同一套展示组件，都从本站 `data/manifest.json` 读取最终数据；筛选及统计区间保留在 URL。显式静态构建用 `NEXT_PUBLIC_SITE_MODE=static` 开启 `output: export` 与 `trailingSlash`，`NEXT_PUBLIC_BASE_PATH` 指定子路径。浏览器不再请求动态 API。

动态详情路由在编译时只生成 `__static__` 模板，构建器按快照清单生成实际地址，并保留 `.static-shells/` 供后续复用。仅数据变化（包含新增对局、选手或赛季）无需重新执行 Next 构建；源码、依赖或构建配置变化仍需编译。公开模式跨页链接使用带 basePath 的原生地址，查询参数变化通过浏览器 history 与 Next hooks 同步，避免向详情模板请求运行时 RSC。

构建成品从根目录调用 `website/static_publish/build_static.py`，完成必要结构和代表页面检查。静态生成文件不纳入源码 Git。网站展示悍跳统计所需的最终次数与成功结果，不公开逐条复核证据、截图或反馈工具。

页脚通过[不蒜子官方服务](https://busuanzi.ibruce.info/)展示累计浏览量（PV）和估算访客数（UV），无需账号或本站后端。数字默认收起，点击“访问统计”在入口右侧同一行显示，再次点击收起；收起不影响正常计数，同页重复展开不重新请求数据。仅在 `https://fengmaker.github.io/langrensha-site/` 的公开页面加载统计脚本，本地预览不发送统计请求。公开模式跨页面使用原生导航，每次页面加载记录一次；同页筛选不重复计数。未取得统计时显示 `—`，不以零替代。

统计自接入后累计，无法补回接入前的访问；UV 按服务规则去重，不等于精确人数。数据由第三方保存，网络或拦截工具可能影响计数。统计按 `fengmaker.github.io` 域名归集，不按 GitHub 项目子路径隔离；重复静态部署或清理本地缓存不会重置计数。

全站共用的 `SiteTraffic` 组件同时接入 [Cloudflare Web Analytics](https://developers.cloudflare.com/web-analytics/get-started/)，使用 `fengmaker.github.io` 统计站点分配的公开 Token，数据在 Cloudflare 后台查看。两套脚本共用上述公开地址限制，本地预览不加载；Cloudflare 设置 `spa: false`，避免同页筛选更新 URL 时被额外计为页面访问。它与不蒜子使用各自的统计口径，数字可能不同。
