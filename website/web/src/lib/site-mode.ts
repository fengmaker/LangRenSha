export const isStaticSite = true;

const configuredBasePath = isStaticSite ? process.env.NEXT_PUBLIC_BASE_PATH ?? "" : "";
export const basePath = configuredBasePath === "/" ? "" : configuredBasePath.replace(/\/$/, "");

/** Add the configured subpath to native browser URLs exactly once. Next Link handles it itself. */
export function publicPath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//") || !basePath) return path;
  if (path === basePath || path.startsWith(`${basePath}/`)) return path;
  return `${basePath}${path}`;
}

export function publicPagePath(path: string): string {
  if (process.env.NEXT_PUBLIC_SITE_MODE !== "static" || !path.startsWith("/") || path.startsWith("//")) return publicPath(path);
  const [pathname] = path.split(/[?#]/, 1);
  const directory = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return publicPath(directory) + path.slice(pathname.length);
}
