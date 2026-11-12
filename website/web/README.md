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
