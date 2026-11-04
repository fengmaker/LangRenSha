import { getOverview } from "@/lib/api";
import { isStaticSite } from "@/lib/site-mode";
import { DataProblem } from "@/components/data-state";
import { HomeView } from "./home-view";
import { StaticHomeBrowser } from "./static-home-browser";

export default async function HomePage() {
  if (isStaticSite) return <StaticHomeBrowser />;
  try {
    return <HomeView data={await getOverview()} />;
  } catch (error) {
    return <div className="page-wrap"><DataProblem error={error} /></div>;
  }
}
