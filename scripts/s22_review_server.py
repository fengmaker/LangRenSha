"""Local, editable S22 review desk with validated transactional saves."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

import batch_s22 as batch
from batch_review import render_game, export_questions
from game_records import import_game, template, validate, ROLE_FACTIONS


def item_data(bvid):
    state = batch.load_state()
    if bvid not in state["items"]:
        raise KeyError("未知对局")
    entry = state["items"][bvid]
    folder = batch.ROOT / entry["output_dir"]
    value = batch.read_json(folder / "dossier.json")
    review_file = folder / "复核记录.json"
    review = batch.read_json(review_file) if review_file.exists() else {"issues": ["原已确认示例，自动补充保留。"]}
    if not review.get("recap_segments") and entry.get("source_path"):
        points = [q for q in review.get("text_review", {}).get("corrections", [])
                  if type(q.get("start_ms")) is int and type(q.get("end_ms")) is int
                  and 0 <= q["end_ms"] - q["start_ms"] < 300_000]
        if points:
            review["recap_segments"] = [s for s in batch.load_segments(batch.ROOT / entry["source_path"])
                if any(s["end_ms"] >= p["start_ms"] - 3000 and s["start_ms"] <= p["end_ms"] + 3000 for p in points)]
            review["context_from_full_transcript"] = True
    return {"entry": entry, "dossier": value, "review": review, "template": template(value["board"]),
            "sha256": batch.digest(folder / "dossier.json"), "role_factions": ROLE_FACTIONS}


def save_item(bvid, payload):
    with batch.batch_lock():
        old = item_data(bvid)
        if payload.get("expected_sha256") != old["sha256"]:
            raise ValueError("这局已被更新，请重新加载后保存，避免覆盖新内容。")
        value = payload["dossier"]
        for field in ("slug", "season", "board", "files"):
            if value.get(field) != old["dossier"].get(field):
                raise ValueError("本入口只修改本局事实，不能更换" + field)
        validate(value, allow_incomplete=True)
        state = batch.load_state()
        entry = state["items"][bvid]
        if entry.get("state") == "preserved":
            raise ValueError("已确认示例已保护，本入口不覆盖。")
        if payload.get("mark_reviewed") is True:
            questions = (old["review"].get("text_review", {}).get("questions", [])
                         + old["review"].get("frame_seats", {}).get("questions", []))
            answers = payload.get("question_answers", {})
            if any(not answers.get(q["id"], {}).get("resolved") for q in questions):
                raise ValueError("请先逐项处理并勾选本局疑点，再标记复核完成。")
        folder = batch.ROOT / entry["output_dir"]
        archive = batch.ROOT / "data/archive/S22_user_review" / bvid / (old["sha256"] + ".json")
        if not archive.exists():
            batch.atomic_json(archive, old["dossier"])
        batch.atomic_json(folder / "dossier.json", value)
        try:
            receipt = import_game(value, allow_incomplete=True)
        except Exception:
            batch.atomic_json(folder / "dossier.json", old["dossier"])
            raise
        file_hash = batch.digest(folder / "dossier.json")
        reviewed = payload.get("mark_reviewed") is True
        status = "reviewed" if reviewed else "imported"
        review = old["review"]
        review.update(state=status, db_receipt=receipt, review_note=str(payload.get("note", "")),
                      question_answers=payload.get("question_answers", {}), user_saved_at=batch.now())
        batch.atomic_json(folder / "database_receipt.json", receipt)
        batch.atomic_json(folder / "复核记录.json", review)
        text_questions = review.get("text_review", {}).get("questions", [])
        entry["text_pending_question_count"] = sum(not review["question_answers"].get(q["id"], {}).get("resolved") for q in text_questions)
        entry["text_resolved_question_count"] = len(text_questions) - entry["text_pending_question_count"]
        entry.update(batch.coverage(value), state=status, auto_protected=True, db_receipt=receipt,
                     imported_dossier_sha256=file_hash, updated_at=batch.now())
        entry["game_number"] = value["game_number"]
        entry.pop("generated_dossier_sha256", None)
        if reviewed:
            entry.update(reviewed_at=batch.now(), review_note=review["review_note"])
        render_game(folder, value, review)
        batch.checkpoint(state, {"bvid": bvid, "stage": "user_review_saved", "reviewed": reviewed})
        export_questions(batch.SEASON_DIR, list(state["items"].values()))
        return item_data(bvid)


class Handler(BaseHTTPRequestHandler):
    server_version = "S22Review/1"

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def json_response(self, value, code=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/games":
                state = batch.load_state()
                progress_file = batch.ROOT / "data/reports/S22_转写逐句复核进度.json"
                progress = batch.read_json(progress_file) if progress_file.exists() else {"items": {}}
                frame_file = batch.ROOT / "data/reports/S22_画面座位补全进度.json"
                frames = batch.read_json(frame_file) if frame_file.exists() else {"items": {}}
                return self.json_response({"items": [{**e, "text_check": progress.get("items", {}).get(e["bvid"], {}),
                                                       "frame_check": frames.get("items", {}).get(e["bvid"], {})}
                                                       for e in state["items"].values()]})
            match = re.fullmatch(r"/api/game/(BV[0-9A-Za-z]+)", path)
            if match:
                return self.json_response(item_data(match[1]))
            if path == "/":
                path = "/data/games/S22/审校工作台.html"
            if not path.startswith(("/data/", "/docs/")):
                return self.send_error(404)
            file = (batch.ROOT / path.lstrip("/")).resolve()
            if not file.is_relative_to(batch.ROOT / "data") and not file.is_relative_to(batch.ROOT / "docs"):
                return self.send_error(403)
            if not file.is_file():
                return self.send_error(404)
            size = file.stat().st_size
            first, last, code = 0, max(0, size - 1), 200
            byte_range = self.headers.get("Range", "")
            if byte_range:
                matched = re.fullmatch(r"bytes=(\d+)-(\d*)", byte_range)
                if not matched:
                    return self.send_error(416)
                first = int(matched[1])
                last = min(int(matched[2]) if matched[2] else size - 1, size - 1)
                if first > last or first >= size:
                    return self.send_error(416)
                code = 206
            self.send_response(code)
            mime = mimetypes.guess_type(file)[0] or "application/octet-stream"
            if file.suffix.lower() in {".html", ".txt", ".csv", ".md", ".json", ".js"}:
                mime += "; charset=utf-8"
            self.send_header("Content-Type", mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            if code == 206:
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            length = 0 if size == 0 else last - first + 1
            self.send_header("Content-Length", str(length))
            self.end_headers()
            if self.command == "HEAD":
                return
            with file.open("rb") as stream:
                stream.seek(first)
                while length:
                    block = stream.read(min(length, 256 * 1024))
                    if not block:
                        break
                    self.wfile.write(block)
                    length -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except KeyError as exc:
            self.json_response({"error": str(exc)}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 500)

    do_HEAD = do_GET

    def do_POST(self):
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/game/(BV[0-9A-Za-z]+)", path)
        if not match:
            return self.send_error(404)
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            return self.send_error(403)
        if self.headers.get_content_type() != "application/json":
            return self.send_error(415)
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 2_000_000:
            return self.send_error(413)
        try:
            payload = json.loads(self.rfile.read(length))
            return self.json_response(save_item(match[1], payload))
        except (ValueError, RuntimeError) as exc:
            return self.json_response({"error": str(exc)}, 409)
        except Exception as exc:
            return self.json_response({"error": type(exc).__name__ + ": " + str(exc)}, 400)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"S22审校工作台：http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()
