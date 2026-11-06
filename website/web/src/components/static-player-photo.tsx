"use client";

import { useEffect, useState } from "react";
import { publicPath } from "@/lib/site-mode";
import type { PlayerPhoto } from "@/lib/types";

export function StaticPlayerPhoto({ photo, alt, priority = "low" }: { photo: PlayerPhoto; alt: string; priority?: "high" | "low" }) {
  const preview = publicPath(photo.url);
  const original = publicPath(photo.original_url ?? photo.url);
  const [loadedPreview, setLoadedPreview] = useState("");
  const [readyOriginal, setReadyOriginal] = useState("");
  const loadOriginal = original !== preview && (priority === "high" || loadedPreview === preview);

  useEffect(() => {
    if (!loadOriginal) return;
    let active = true;
    const image = new Image();
    image.fetchPriority = priority;
    image.decoding = "async";
    image.src = original;
    image.decode().then(() => { if (active) setReadyOriginal(original); })
      .catch(() => { /* Keep the visible preview when the original cannot load. */ });
    return () => {
      active = false;
      image.removeAttribute("src");
    };
  }, [original, loadOriginal, priority]);

  return <img
    src={readyOriginal === original ? original : preview}
    alt={alt}
    loading={priority === "high" ? "eager" : "lazy"}
    decoding="async"
    fetchPriority={readyOriginal === original ? priority : "auto"}
    onLoad={() => setLoadedPreview(preview)}
    onError={() => setLoadedPreview(preview)}
  />;
}
