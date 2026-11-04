"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { isStaticSite } from "@/lib/site-mode";

type ArchiveLinkProps = ComponentProps<typeof Link>;

export function ArchiveLink(props: ArchiveLinkProps) {
  return <Link {...props} prefetch={isStaticSite ? false : props.prefetch} />;
}
