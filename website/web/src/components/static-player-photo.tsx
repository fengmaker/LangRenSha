"use client";

import { useEffect, useState } from "react";
import { publicPath } from "@/lib/site-mode";
import type { PlayerPhoto } from "@/lib/types";

export function StaticPlayerPhoto({ photo, alt }: { photo: PlayerPhoto; alt: string }) {
  const preview = publicPath(photo.url);
  const original = publicPath(photo.original_url ?? photo.url);
  const [readyOriginal, setReadyOriginal] = useState("");

  useEffect(() => {
    if (original === preview) return;
    let active = true;
    const image = new Image();
    image.fetchPriority = "high";
    image.decoding = "async";
    image.src = original;
    image.decode().then(() => { if (active) setReadyOriginal(original); })
      .catch(() => { /* Keep the visible preview when the original cannot load. */ });
    return () => {
      active = false;
      image.removeAttribute("src");
    };
  }, [original, preview]);

  return <img
    src={readyOriginal === original ? original : preview}
    alt={alt}
    loading="eager"
    decoding="async"
    fetchPriority={readyOriginal === original ? "high" : "auto"}
  />;
}
