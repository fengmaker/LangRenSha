"use client";

import { StaticData } from "@/components/static-data";
import { fetchOverview } from "@/lib/static-browser";
import { HomeView } from "./home-view";

export function StaticHomeBrowser() {
  return <StaticData load={fetchOverview}>{(data) => <HomeView data={data} />}</StaticData>;
}
