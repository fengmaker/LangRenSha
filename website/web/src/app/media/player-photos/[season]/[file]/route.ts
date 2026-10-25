const filePattern = /^[a-f0-9]{64}\.(jpg|jpeg|png|webp)$/;

export async function GET(_request: Request, { params }: { params: Promise<{ season: string; file: string }> }) {
  const { season, file } = await params;
  if (!/^S[0-9]{1,4}$/.test(season) || !filePattern.test(file)) {
    return new Response(null, { status: 404 });
  }
  const base = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  try {
    const result = await fetch(`${base}/api/v1/photos/${season}/${file}`, {
      cache: "no-store", signal: AbortSignal.timeout(10000),
    });
    if (!result.ok) return new Response(null, { status: result.status === 404 ? 404 : 502 });
    const headers = new Headers({
      "Content-Type": result.headers.get("content-type") ?? "image/jpeg",
      "Cache-Control": "public, max-age=31536000, immutable",
      "X-Content-Type-Options": "nosniff",
    });
    const tag = result.headers.get("etag");
    if (tag) headers.set("ETag", tag);
    return new Response(result.body, { headers });
  } catch {
    return new Response(null, { status: 502 });
  }
}
