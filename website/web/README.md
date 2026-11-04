# Next.js前端

先读本目录[AGENTS规范](AGENTS.md)；涉及框架约定时读安装版Next本地指南。

- `src/app/`按路由组织页面及专属样式；`layout.tsx/globals.css/interface.css`控制全站结构与通用视觉。
- `src/components/`是跨页复用的导航、座位、事件、票型和榜单交互。
- `src/lib/api.ts`封装只读API，`types.ts`保存前端响应类型，`format.ts`只负责显示格式。
- 图片使用 `public/media` 中API清单允许的实体文件；本地启动器同步媒体，standalone复制public目录。
- `node_modules/`是安装依赖，`.next/`是本地维护构建，`.static-build/`是公开静态构建的独立工作目录，均不编辑。

本目录执行`npm ci`、`npm run typecheck`、`npm run build`。从项目根通过[run.py](../run.py)启动，与API配对；完整流程见[网站说明](../README.md)。

日常同步入口为项目根的 `website/static_publish/sync_pages.py`，完整操作见[静态发布说明](../static_publish/README.md)。静态构建入口复制同一份源码及配置到 `.static-build/`，在那里执行构建和类型检查，依赖复用父目录安装，无需再安装一套。

静态构建使用同一套展示组件。`NEXT_PUBLIC_SITE_MODE=static` 开启 `output: export` 与 `trailingSlash`，`NEXT_PUBLIC_BASE_PATH` 固定项目子路径；这些值只由 `build_static.py` 设置到构建子进程。公开 HTML 和脚本不嵌入比赛快照，浏览器从本站 `data/manifest.json` 选择当前快照并读取 JSON，筛选及统计区间保留在 URL。本地维护模式仍通过 API 服务端取数。

动态详情路由在编译时只生成 `__static__` 模板，构建器按快照清单生成实际地址，并保留 `.static-shells/` 供后续复用。仅数据变化（包含新增对局、选手或赛季）无需重新执行 Next 构建；源码、依赖或构建配置变化仍需编译。公开模式跨页链接使用带 basePath 的原生地址，查询参数变化通过浏览器 history 与 Next hooks 同步，避免向详情模板请求运行时 RSC。

导出、必要的构建／类型检查及验收从根目录调用 `website/static_publish/build_static.py`，不要把单独的 `out/` 当作已验收成品。默认只做小范围浏览器验收；`--skip-browser-check` 只跳过这一层，文件和 API 检查继续运行。静态生成文件不纳入源码 Git。公开模式隐藏反馈维护控件；默认本地模式保留草稿保存、导入和导出。
