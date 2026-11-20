import type { Metadata } from "next";
import { StaticSeasonBrowser } from "./static-season-browser";

export const metadata: Metadata = { title: "赛季档案" };
export const generateStaticParams = async () => [{ id: "__static__" }];

export default function SeasonPage() {
  return <StaticSeasonBrowser />;
}
