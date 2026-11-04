import type { NextConfig } from "next";
import path from "node:path";

const staticSite = process.env.NEXT_PUBLIC_SITE_MODE === "static";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  output: staticSite ? "export" : "standalone",
  trailingSlash: staticSite,
  basePath: staticSite ? basePath : "",
  ...(staticSite ? { turbopack: { root: path.resolve(process.cwd(), "..") } } : {}),
  images: { unoptimized: true },
};

export default nextConfig;
