export const isStaticSite = process.env.NEXT_PUBLIC_SITE_MODE === "static";

const configuredBasePath = isStaticSite ? process.env.NEXT_PUBLIC_BASE_PATH ?? "" : "";
export const basePath = configuredBasePath === "/" ? "" : configuredBasePath.replace(/\/$/, "");

/** Add the configured subpath to native browser URLs exactly once. Next Link handles it itself. */
export function publicPath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//") || !basePath) return path;
  if (path === basePath || path.startsWith(`${basePath}/`)) return path;
  return `${basePath}${path}`;
}
