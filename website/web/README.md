# Next.js前端

先读本目录[AGENTS规范](AGENTS.md)；涉及框架约定时读安装版Next本地指南。

- `src/app/`按路由组织页面及专属样式；`layout.tsx/globals.css/interface.css`控制全站结构与通用视觉。
- `src/components/`是跨页复用的导航、座位、事件、票型和榜单交互。
- `src/lib/api.ts`封装只读API，`types.ts`保存前端响应类型，`format.ts`只负责显示格式。
- 图片使用 `public/media` 中API清单允许的实体文件；本地启动器同步媒体，standalone复制public目录。
- `node_modules/`是安装依赖，`.next/`是生成构建，不编辑；运行中standalone目录在Windows可能锁定。

本目录执行`npm ci`、`npm run typecheck`、`npm run build`。从项目根通过[run.py](../run.py)启动，与API配对；完整流程见[网站说明](../README.md)。

静态构建使用同一套展示组件。`NEXT_PUBLIC_SITE_MODE=static` 开启 `output: export` 与 `trailingSlash`，`NEXT_PUBLIC_BASE_PATH` 固定项目子路径；这些值只由 `build_static.py` 设置到构建子进程。服务端从 `.static-snapshot/data` 生成HTML，浏览器仅读取本站 `public/data` 的JSON，筛选及统计区间保留在URL。原生图片／fetch路径通过公共路径函数添加basePath，Next Link继续使用站内路径。

完整导出、构建、类型检查及浏览器验收从根目录调用 `website/build_static.py`，不要把单独的 `out/` 当作已验收成品。静态生成文件不纳入源码Git。公开模式隐藏反馈维护控件；默认本地模式保留草稿保存、导入和导出。
