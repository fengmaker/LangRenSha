"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { isStaticSite, publicPath } from "@/lib/site-mode";

type ArchiveLinkProps = ComponentProps<"a"> & { href: string };

export function ArchiveLink({ href, onClick, ...props }: ArchiveLinkProps) {
  if (!isStaticSite) return <Link {...props} href={href} onClick={onClick} />;
  return <a {...props} href={publicPath(href)} onClick={(event) => {
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
