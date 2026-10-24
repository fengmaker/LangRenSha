"""Resumable official S22 audio/subtitle acquisition and readable season archive."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import threading
import time

import psycopg
from psycopg.types.json import Jsonb
import requests

from auth_support import AuthConfigurationError
from collect_bilibili_audio import CollectionError, Collector, save_json
import database
from export_collection_index import export
from media_ingest import MediaValidationError, OFFICIAL_BILIBILI_MID, validate_media
from season_naming import export_source, naming, validate_cues

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/"data/indexes/S22_采集计划.json"
STATE = ROOT/"data/reports/S22_采集进度.json"
COLLECTION_ID = 8209896


class Throttle:
    def __init__(self,interval: float):
        self.interval,self.previous,self.lock = interval,0.0,threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.interval-(time.monotonic()-self.previous)
            if delay>0:
                time.sleep(delay)
            self.previous=time.monotonic()


class BatchCollector(Collector):
    def __init__(self,auth,cookies,throttle,stop):
        super().__init__(auth,cookies,quiet=True)
        self.throttle,self.stop=throttle,stop

    def api(self,path,params):
        if self.stop.is_set():
            raise CollectionError("批次已经停止，未继续请求")
        self.throttle.wait()
        if self.stop.is_set():
            raise CollectionError("批次已经停止，未继续请求")
        try:
            return super().api(path,params)
        except CollectionError as error:
            if any(token in str(error) for token in ["HTTP 403","HTTP 429","HTTP 412","业务状态 -412","业务状态 -352","业务状态 -799"]):
                self.stop.set()
            raise


def build_plan(auth: str,cookies: Path | None) -> dict:
    collector=Collector(auth,cookies,quiet=True)
    raw=collector.api("/x/web-interface/view",{"bvid":"BV1tj8p6REqy"})
    view=raw["data"]
    collection=view.get("ugc_season") or {}
    if str(view["owner"]["mid"]) != OFFICIAL_BILIBILI_MID or collection.get("id") != COLLECTION_ID or str(collection.get("mid")) != OFFICIAL_BILIBILI_MID:
        raise ValueError("不是目标官方 S22 合集")
    raw_path=ROOT/"data/raw/bilibili/S22_collection.view.raw.json"
    save_json(raw_path,raw)
    csv_path=ROOT/"data/indexes/S22_官方合集_候选索引.csv"
    export(raw_path,csv_path)
    rows=list(csv.DictReader(csv_path.open(encoding="utf-8-sig",newline="")))
    if len(rows) != collection.get("ep_count"):
        raise ValueError("返回条目数与官方合集声明数量不一致，未开始批量下载")
    keys={(row["bvid"],row["cid"]) for row in rows}
    if len(keys) != len(rows):
        raise ValueError("合集含重复 BV/CID，需先核对目录")
    opening=min(row["event_date_candidate"] for row in rows if row["phase_candidate"]=="showmatch" and row["event_date_candidate"])
    anchor=datetime.strptime(opening,"%Y%m%d").date().isoformat()
    entries=[]
    for index,row in enumerate(rows,start=1):
        entry={"index":index,"bvid":row["bvid"],"cid":int(row["cid"]),"page":int(row["page"] or 1),
               "title":row["title"],"duration_seconds":int(row["duration_seconds"] or 0)}
        entry["labels"]=naming(entry["title"],entry["bvid"],entry["cid"],entry["page"],anchor)
        entries.append(entry)
    value={"schema_version":1,"season":"S22","collection_id":COLLECTION_ID,"collection_title":collection["title"],
           "owner_mid":OFFICIAL_BILIBILI_MID,"created_at_utc":datetime.now(timezone.utc).isoformat(),
           "collection_source":raw_path.relative_to(ROOT).as_posix(),"anchor":anchor,
           "declared_count":collection["ep_count"],"entry_count":len(entries),"entries":entries,
           "coverage_note":"完整保存本次官方合集实际返回的媒体条目；不保证已找齐合集外、已删除或未公开的历史对局。",
           "total_duration_seconds":sum(item["duration_seconds"] for item in entries)}
    save_json(PLAN,value)
    return value


def source_key(entry: dict) -> str:
    return f"{entry['bvid']}:{entry['cid']}"


def record_success(entry: dict,manifest_path: Path,anchor: str,cached: bool) -> dict:
    checked=validate_media(manifest_path,entry["bvid"],entry["page"])
    manifest=checked["manifest"]
    if manifest["cid"] != entry["cid"]:
        raise ValueError("当前 CID 与冻结的合集清单不符")
    labels=naming(manifest["title"],entry["bvid"],entry["cid"],entry["page"],anchor)
    result=export_source(manifest_path,labels)
    if not cached:
        manifest["collection_context"]={"season":"S22","collection_id":COLLECTION_ID,"labels":labels,"exports":result}
        save_json(manifest_path,manifest)
        registered=database.import_media(manifest_path,entry["bvid"],entry["page"])
        source_id=registered["source_id"]
    else:
        with database.connect() as conn:
            row=conn.execute("SELECT id FROM sources WHERE platform='bilibili' AND external_key=%s",(source_key(entry),)).fetchone()
        if row is None:
            registered=database.import_media(manifest_path,entry["bvid"],entry["page"])
            source_id=registered["source_id"]
        else:
            source_id=str(row["id"])
    tracks=result["subtitles"]
    return {"status":"complete" if tracks else "audio_only","bvid":entry["bvid"],"cid":entry["cid"],
            "source_id":source_id,"audio_bytes":manifest["audio"]["bytes"],"audio_sha256":manifest["audio"]["sha256"],
            "subtitle_status":(manifest.get("subtitles") or {}).get("status"),
            "subtitle_tracks":len(tracks),"subtitle_segments":sum(track["segment_count"] for track in tracks),
            "labels":labels,"exports":result,"cached":cached,"finished_at_utc":datetime.now(timezone.utc).isoformat()}


def collect_one(entry,previous,anchor,auth,cookies,throttle,stop,refresh_subtitles=False):
    if stop.is_set():
        return {"status":"pending","bvid":entry["bvid"],"cid":entry["cid"],"reason":"批次停止，未继续请求"}
    path=ROOT/"data/raw/bilibili"/entry["bvid"]/f"p{entry['page']:02d}"/"manifest.json"
    if previous and previous.get("status")=="complete" and not refresh_subtitles:
        try:
            return record_success(entry,path,anchor,cached=True)
        except (ValueError,OSError,psycopg.Error):
            pass
    if shutil.disk_usage(ROOT).free < 8*1024**3:
        stop.set()
        return {"status":"failed","bvid":entry["bvid"],"cid":entry["cid"],"reason":"磁盘剩余不足 8 GiB，已停止"}
    for attempt in range(2):
        try:
            collector=BatchCollector(auth,cookies,throttle,stop)
            collector.collect(entry["bvid"],entry["page"],ROOT/"data/raw/bilibili",True,128000,200*1024**2,
                              expected_owner=OFFICIAL_BILIBILI_MID)
            return record_success(entry,path,anchor,cached=False)
        except (requests.Timeout,requests.ConnectionError) as error:
            if attempt==0 and not stop.is_set():
                time.sleep(3)
                continue
            return {"status":"failed","bvid":entry["bvid"],"cid":entry["cid"],"reason":type(error).__name__}
        except (CollectionError,AuthConfigurationError,MediaValidationError,database.ReviewError,ValueError) as error:
            return {"status":"blocked" if stop.is_set() else "failed","bvid":entry["bvid"],"cid":entry["cid"],"reason":str(error)}
        except (OSError,psycopg.Error,requests.RequestException,KeyError,TypeError) as error:
            return {"status":"failed","bvid":entry["bvid"],"cid":entry["cid"],"reason":type(error).__name__}


def write_inventory(plan,state):
    target=ROOT/"data/seasons/S22"
    target.mkdir(parents=True,exist_ok=True)
    rows=[]
    for entry in plan["entries"]:
        result=state["items"].get(source_key(entry),{})
        labels=result.get("labels") or entry["labels"]
        exports=result.get("exports") or {}
        tracks=exports.get("subtitles") or []
        rows.append({"目录序号":entry["index"],"状态":result.get("status","pending"),"标题日期候选":labels["event_date_candidate"],
                     "归档周次":labels["week_number"],"阶段候选":labels["phase_label"],"正赛期次候选":labels["issue_candidate"],
                     "局次候选":labels["game_number_candidate"],"配置候选":labels["board_candidate"],"原始标题":entry["title"],
                     "BVID":entry["bvid"],"CID":entry["cid"],"分P":entry["page"],"音频文件":exports.get("audio"),
                     "音频字节数":result.get("audio_bytes"),"字幕段数":result.get("subtitle_segments"),
                     "字幕状态":result.get("subtitle_status"),"字幕原件":" | ".join(track["raw"] for track in tracks),
                     "SRT":" | ".join(track["srt"] for track in tracks),"阅读版":" | ".join(track["readable"] for track in tracks),
                     "待核事项":" | ".join(labels["warnings"]),"错误":result.get("reason","")})
    temporary=target/"S22_音频与字幕总目录.csv.tmp"
    with temporary.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    temporary.replace(target/"S22_音频与字幕总目录.csv")
    counts=Counter(row["状态"] for row in rows)
    state["summary"]={"planned":len(rows),"status_counts":dict(counts),
                      "audio_ready":sum(row["状态"] in {"complete","audio_only"} for row in rows),
                      "with_subtitles":counts.get("complete",0),
                      "audio_bytes":sum(row["音频字节数"] or 0 for row in rows),
                      "subtitle_segments":sum(row["字幕段数"] or 0 for row in rows)}
    state["updated_at_utc"]=datetime.now(timezone.utc).isoformat()
    save_json(STATE,state)
    save_json(target/"S22_音频与字幕总目录.json",{"plan_metadata":{k:v for k,v in plan.items() if k!="entries"},"summary":state["summary"],"entries":rows})


def run(plan,auth,cookies,workers,refresh_subtitles=False):
    # Fail early on invalid auth/DB instead of discovering it after hundreds of downloads.
    Collector(auth,cookies,quiet=True)
    with database.connect() as conn:
        conn.execute("SELECT 1 FROM sources LIMIT 1")
    state=json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"season":"S22","items":{}}
    if state.get("collection_id",COLLECTION_ID)!=plan["collection_id"]:
        raise ValueError("旧进度不是同一个合集")
    state["collection_id"]=plan["collection_id"]
    state["current_run"]={"started_at_utc":datetime.now(timezone.utc).isoformat(),"refresh_subtitles":refresh_subtitles,
                          "processed":0,"planned":len(plan['entries']),"state":"running"}
    stop=threading.Event();throttle=Throttle(1.25)
    write_inventory(plan,state)
    print(f"S22 待核对/采集 {len(plan['entries'])} 条；线程 {workers}；API 全局间隔 1.25 秒",flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(collect_one,entry,state["items"].get(source_key(entry)),plan["anchor"],auth,cookies,throttle,stop,refresh_subtitles):entry for entry in plan["entries"]}
        for future in as_completed(futures):
            entry=futures[future]
            result=future.result()
            # Do not erase a previously completed item when a later run is stopped.
            if result["status"]!="pending" or source_key(entry) not in state["items"]:
                state["items"][source_key(entry)]=result
            state["current_run"]["processed"]+=1
            state["current_run"]["last_bvid"]=entry["bvid"]
            write_inventory(plan,state)
            summary=state["summary"]
            print(f"[本轮{state['current_run']['processed']}/{summary['planned']}，音频{summary['audio_ready']}/{summary['planned']}] {entry['bvid']} {result['status']} 字幕{result.get('subtitle_segments',0)}段 {result.get('reason','')}",flush=True)
    state["run_finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    state["current_run"]["state"]="finished"
    write_inventory(plan,state)
    print(json.dumps(state["summary"],ensure_ascii=False,indent=2),flush=True)
    return 0 if state["summary"]["audio_ready"]==len(plan["entries"]) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["plan","run","status"])
    parser.add_argument("--auth",choices=["none","cookies"],default="none")
    parser.add_argument("--cookies-file",type=Path)
    parser.add_argument("--workers",type=int,choices=[1,2,3],default=2)
    parser.add_argument("--refresh-subtitles",action="store_true",help="统一刷新已完成条目的字幕，仍复用已有音轨")
    args=parser.parse_args()
    if args.action=="plan":
        value=build_plan(args.auth,args.cookies_file)
        print(json.dumps({"plan":str(PLAN.relative_to(ROOT)),"entries":value["entry_count"],"hours":value["total_duration_seconds"]/3600},ensure_ascii=False,indent=2))
    elif args.action=="status":
        state=json.loads(STATE.read_text(encoding="utf-8"))
        print(json.dumps({**state["summary"],"current_run":state.get("current_run")},ensure_ascii=False,indent=2))
    else:
        raise SystemExit(run(json.loads(PLAN.read_text(encoding="utf-8")),args.auth,args.cookies_file,args.workers,args.refresh_subtitles))


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8");sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (AuthConfigurationError,CollectionError,ValueError,OSError,psycopg.Error,requests.RequestException) as error:
        message=str(error) if isinstance(error,(AuthConfigurationError,CollectionError,ValueError)) else type(error).__name__
        print("采集停止："+message,file=sys.stderr)
        raise SystemExit(1)
