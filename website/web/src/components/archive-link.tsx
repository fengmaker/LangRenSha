"use client";

import type { ComponentProps } from "react";
import { publicPagePath } from "@/lib/site-mode";

type ArchiveLinkProps = ComponentProps<"a"> & { href: string };

export function ArchiveLink({ href, onClick, ...props }: ArchiveLinkProps) {
  return <a {...props} href={publicPagePath(href)} onClick={(event) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || (props.target && props.target !== "_self") || props.download !== undefined) return;
    const target = new URL(event.currentTarget.href);
    const current = new URL(window.location.href);
    if (target.origin === current.origin && target.pathname.replace(/\/$/, "") === current.pathname.replace(/\/$/, "") && !target.hash) {
      event.preventDefault();
      window.history.pushState(null, "", target.href);
    }
  }} />;
}
