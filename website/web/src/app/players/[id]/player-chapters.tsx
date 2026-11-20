"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./player-detail.module.css";

export const profileChapters = {
  overview: { id: "profile-overview", label: "综合" },
  good: { id: "profile-good", label: "好人" },
  divine: { id: "profile-divine", label: "神职" },
  wolf: { id: "profile-wolf", label: "狼人" },
  lifecycle: { id: "profile-lifecycle", label: "受袭与出局" },
  roles: { id: "profile-roles", label: "身份胜率" },
  boards: { id: "profile-boards", label: "版型胜率" },
  games: { id: "profile-games", label: "对局记录" },
} as const;
const chapters = Object.entries(profileChapters);

export function PlayerChapterNav() {
  const nav = useRef<HTMLElement>(null);
  const [active, setActive] = useState<string>(profileChapters.overview.id);

  useEffect(() => {
    const sections = chapters.flatMap(([, { id }]) => {
      const section = document.getElementById(id);
      return section ? [section] : [];
    });
    let frame = 0;

    function updateActive() {
      frame = 0;
      const offset = Math.max(0, nav.current?.getBoundingClientRect().bottom ?? 0) + 28;
      const atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
      const section = atBottom ? sections.at(-1) : sections.findLast((item) => item.getBoundingClientRect().top <= offset);
      setActive(section?.id ?? profileChapters.overview.id);
    }

    function scheduleUpdate() {
      if (!frame) frame = window.requestAnimationFrame(updateActive);
    }

    // The profile is loaded after the document, so its anchor may not exist on the browser's first attempt.
    const initialHash = window.location.hash.slice(1);
    sections.find(({ id }) => id === initialHash)?.scrollIntoView({ block: "start", behavior: "instant" });
    scheduleUpdate();
    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    window.addEventListener("hashchange", scheduleUpdate);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
      window.removeEventListener("hashchange", scheduleUpdate);
    };
  }, []);

  return <nav ref={nav} className={styles.chapterNav} aria-label="选手档案章节">
    {chapters.map(([tone, { id, label }]) => <a key={id} href={`#${id}`}
      data-profile-tone={tone} aria-current={active === id ? "location" : undefined}>{label}</a>)}
  </nav>;
}
