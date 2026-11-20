import { readFile } from "node:fs/promises";
import path from "node:path";
import type { SnapshotManifest } from "./types";

export async function readPageSnapshot() {
  const dataRoot = process.env.ARCHIVE_PRERENDER_DATA ?? path.join(process.cwd(), "public", "data");
  async function readJson<T>(file: string): Promise<T> {
    return JSON.parse(await readFile(path.join(dataRoot, file), "utf8")) as T;
  }

  const manifest = await readJson<SnapshotManifest>("manifest.json");
  return {
    manifest,
    read: <T>(file: string) => readJson<T>(path.join("releases", manifest.snapshot_id, file)),
  };
}
