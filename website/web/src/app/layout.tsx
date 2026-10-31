import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import "./globals.css";
import "./interface.css";

export const metadata: Metadata = {
  title: { default: "大师赛档案", template: "%s · 大师赛档案" },
  description: "面向狼人杀大师赛的独立数据档案，整理对局、选手、身份、票型与事件记录。",
};

export const viewport: Viewport = { themeColor: "#071011" };

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return <html lang="zh-CN"><body><a className="skip-link" href="#main-content">跳到主要内容</a><SiteHeader /><main id="main-content" className="site-main" tabIndex={-1}>{children}</main><SiteFooter /></body></html>;
}
