# Next.js前端

先读本目录[AGENTS规范](AGENTS.md)；涉及框架约定时读安装版Next本地指南。

- `src/app/`按路由组织页面及专属样式；`layout.tsx/globals.css/interface.css`控制全站结构与通用视觉。
- `src/components/`是跨页复用的导航、座位、事件、票型和榜单交互。
- `src/lib/api.ts`封装只读API，`types.ts`保存前端响应类型，`format.ts`只负责显示格式。
- 图片同源路由转发API清单允许的资产，不从原始data读取照片。
- `node_modules/`是安装依赖，`.next/`是生成构建，不编辑；运行中standalone目录在Windows可能锁定。

本目录执行`npm ci`、`npm run typecheck`、`npm run build`。从项目根通过[run.py](../run.py)启动，与API配对；完整流程见[网站说明](../README.md)。
