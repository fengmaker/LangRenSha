import { readPageSnapshot } from "@/lib/static-page-data";
import type { Overview } from "@/lib/types";
import { HomeView } from "./home-view";

export default async function HomePage() {
  const snapshot = await readPageSnapshot();
  return <HomeView data={await snapshot.read<Overview>("overview.json")} />;
}
