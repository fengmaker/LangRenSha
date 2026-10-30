# 实现职责索引

只在定位实现时阅读本页；日常阶段入口见[README](README.md)。这是现有模块职责表，不是从头执行的脚本清单。

## 统一入口与运行环境

| 文件 | 职责 |
| --- | --- |
| [backup_database.py](backup_database.py) | Back up the whole database and record every retained season's source baseline. |
| [cleanup_data.py](cleanup_data.py) | Offline cleanup preview: preserve active season media and registered evidence. |
| [database.py](database.py) | Migrations, provenance ingestion and explicit local review for the pilot game. |
| [local_postgres.py](local_postgres.py) | Project-local PostgreSQL for Windows; no service or global PATH changes. |
| [season_config.py](season_config.py) | Shared registry for season metadata and existing season-specific profiles. |
| [workflow.py](workflow.py) | Inspect progress, preview or execute a named season stage; no task template. |

## 采集、来源与命名

| 文件 | 职责 |
| --- | --- |
| [auth_support.py](auth_support.py) | Explicit, opt-in loading of platform-scoped Netscape cookies. |
| [collect_bilibili_audio.py](collect_bilibili_audio.py) | Collect Bilibili metadata, visible subtitles, and an optional separate audio track. |
| [collect_official_audio.py](collect_official_audio.py) | Explicit audio validation and raw-source registration, separate from file-only collection. |
| [collect_season.py](collect_season.py) | Sequential local season collection: Chinese subtitles first, audio only when no Chinese track is accessible. |
| [collect_weibo.py](collect_weibo.py) | Collect a bounded sample of publicly visible Weibo posts. |
| [collect_weibo_archive.py](collect_weibo_archive.py) | Resume a dated Weibo archive, reusing existing posts and media. |
| [export_collection_index.py](export_collection_index.py) | Export L0 candidates from a saved Bilibili view response; no network access. |
| [export_weibo_schedule.py](export_weibo_schedule.py) | Export an offline, reviewable schedule index from a collected Weibo manifest. |
| [login_session.py](login_session.py) | Export reusable platform cookies from an existing Chrome or isolated profile. |
| [media_ingest.py](media_ingest.py) | Validate a downloaded official audio source without loading an ASR model. |
| [season_naming.py](season_naming.py) | Human-readable source labels and subtitle exports, never verified game facts. |
| [weibo_naming.py](weibo_naming.py) | Stable, human-readable names for archived Weibo post artifacts. |

## 转写、复盘定位与模型比较

| 文件 | 职责 |
| --- | --- |
| [audit_full_transcripts.py](audit_full_transcripts.py) | Independent final checks for the authorized S22 full-audio ASR batch. |
| [benchmark_funasr_models.py](benchmark_funasr_models.py) | Run Paraformer/Nano on the fixed local ASR comparison corpus. |
| [extract_audio_window.py](extract_audio_window.py) | Seek to a local audio window and save mono 16 kHz PCM with original offsets. |
| [plan_recap_windows.py](plan_recap_windows.py) | Build a conservative, subtitle-guided plan for local recap transcription. |
| [prepare_asr_benchmark_corpus.py](prepare_asr_benchmark_corpus.py) | Prepare a small, independently reviewable ASR benchmark corpus. |
| [register_season_transcripts.py](register_season_transcripts.py) | Register selected platform/local transcripts in the existing raw-text schema. |
| [review_asr_clip.py](review_asr_clip.py) | Review one short audio window with the retained local Fun-ASR-Nano model. |
| [summarize_asr_benchmark.py](summarize_asr_benchmark.py) | Package a completed local ASR benchmark without treating machine text as gold. |
| [transcribe_funasr.py](transcribe_funasr.py) | Transcribe one local recording with Paraformer, VAD, punctuation and CAM++. |
| [transcribe_review_queue.py](transcribe_review_queue.py) | Batch full-audio FunASR for the selected season's review queue. |
| [validate_asr_benchmark.py](validate_asr_benchmark.py) | Validate the saved, local three-model ASR comparison artifacts. |

## 身份、日夜、票型与规则

| 文件 | 职责 |
| --- | --- |
| [board_catalog.py](board_catalog.py) | Canonical title lookup for S22 board templates. |
| [board_config.py](board_config.py) | Load shared board templates and existing storage-code variants. |
| [endgame_records.py](endgame_records.py) | Generate independent, source-bound S22 wolf-rush endgame sidecars. |
| [formal_entry.py](formal_entry.py) | Create, check, import and audit scored S22 entries using the formal rulebook. |
| [formal_rule_checks.py](formal_rule_checks.py) | Known-rule checks for scored S22 boards; never infer an unobserved result. |
| [game_flow.py](game_flow.py) | Replay departures at their actual phase; keep deductions outside source facts. |
| [game_parser.py](game_parser.py) | Build conservative, review-only game-structure candidates from ASR JSON. |
| [game_records.py](game_records.py) | Current game records: shared people and fixed per-board event slots. |
| [game_scope.py](game_scope.py) | User-selected scope for structured game records; raw media stays independent. |
| [recap_parser.py](recap_parser.py) | Conservative, deterministic parsing of an already located referee recap. |
| [recap_specials.py](recap_specials.py) | Conservative extraction of explicit special-board recap actions. |
| [rule_config.py](rule_config.py) | Load shared rules and season scope, rotation and import settings. |
| [voting_crosscheck.py](voting_crosscheck.py) | Reconcile announced voting outcomes with the independent referee recap. |
| [voting_records.py](voting_records.py) | Extract announced ballots from full transcripts; keep evidence outside game facts. |
| [voting_rules.py](voting_rules.py) | Apply user-confirmed S22 election and default-abstention rules after source corrections. |

## 按季复核适配和校验

| 文件 | 职责 |
| --- | --- |
| [audit_s22_batch.py](audit_s22_batch.py) | Read-only comparison of S22 dossiers, batch receipts and PostgreSQL facts. |
| [audit_s22_frame_seats.py](audit_s22_frame_seats.py) | Read-only acceptance audit for S22 same-day frame seat names. |
| [audit_s22_text_review.py](audit_s22_text_review.py) | Check transcript-only supplementation, resumable state and review entries. |
| [audit_s23_review.py](audit_s23_review.py) | Validate review candidates and evidence, without writing formal game tables. |
| [audit_season.py](audit_season.py) | Offline completeness and subtitle-coverage audit for a downloaded season archive. |
| [audit_weibo_archive.py](audit_weibo_archive.py) | Verify an archived date window and write a readable artifact catalog. |
| [audit_weibo_identity_mapping.py](audit_weibo_identity_mapping.py) | Optional consistency audit of the existing S22/S23 schedule, reviewed name/photo map and formal-name photo coverage; no new visual review. |
| [batch_people.py](batch_people.py) | Conservative local enrichment of batch S22 names and seat assignments. |
| [batch_review.py](batch_review.py) | Render local batch-review pages and CSV exports for S22 game dossiers. |
| [batch_s22.py](batch_s22.py) | Recap-first S22 imports, separate review files, and resumable checkpoints. |
| [check_bluff_feedback_export.py](check_bluff_feedback_export.py) | Exercise the real S22 feedback forms in a disposable offline browser page. |
| [check_s23_bluff_review.py](check_s23_bluff_review.py) | Check the finished S23 review artifact, image evidence, feedback and live page. |
| [check_s23_daily_audit.py](check_s23_daily_audit.py) | Verify daily-audit coverage, exact quote locations and recap-only exports. |
| [check_s23_database_preservation.py](check_s23_database_preservation.py) | Compare S22 source database content before and after an S23 import. |
| [check_s23_phase_consistency.py](check_s23_phase_consistency.py) | Cross-check definite departures against recorded S23 voter eligibility. |
| [check_s23_phase_review.py](check_s23_phase_review.py) | Check the user's death/skill, vote-control and per-phase review scenarios. |
| [check_s23_review_page.py](check_s23_review_page.py) | Exercise local S23 review navigation, feedback round-trip and source links. |
| [check_weibo_name_review.mjs](check_weibo_name_review.mjs) | 辅助工具；仅对应专项任务时使用。 |
| [consolidate_s22_day_seats.py](consolidate_s22_day_seats.py) | Consolidate confirmed S22 seat-name evidence within each game day. |
| [import_s23_formal.py](import_s23_formal.py) | Prepare, validate, and atomically import the current S23 formal snapshot. |
| [prepare_s23_review.py](prepare_s23_review.py) | Prepare evidence packets and candidate dossiers; never import game facts. |
| [prune_s22_excluded.py](prune_s22_excluded.py) | Remove user-excluded S22 games from the database and active review artifacts. |
| [reconcile_s22_day_flow.py](reconcile_s22_day_flow.py) | Apply the sourced S22 treasure alignment and confirmed no-exile day correction. |
| [reconcile_season_subtitles.py](reconcile_season_subtitles.py) | Select the best existing Chinese capture without network requests or text edits. |
| [review_s22_voting.py](review_s22_voting.py) | Audit current voting facts and build a dated, evidence-linked review queue. |
| [s22_frame_seats.py](s22_frame_seats.py) | Import S22 seat names read from per-game video frames. |
| [s22_inference_review.py](s22_inference_review.py) | Validate and apply evidence-backed S22 AI doubt reviews through the review save seam. |
| [s22_review_server.py](s22_review_server.py) | Local, editable S22 review desk with validated transactional saves. |
| [s22_text_review.py](s22_text_review.py) | Apply source-bound, sentence-by-sentence S22 transcript review without video. |
| [s23_bluff_audit.py](s23_bluff_audit.py) | Validate independent S23 speech/frame reviews without inferring claims by keywords. |
| [s23_daily_audit.py](s23_daily_audit.py) | Apply source-bound daily audits without replacing original review records. |
| [s23_endgames.py](s23_endgames.py) | Source-bound S23 endgame candidates; no database import entry point. |
| [s23_phase_review.py](s23_phase_review.py) | Attach explicit per-phase gaps and mixed-blood vote arithmetic to S23 reviews. |
| [s23_schema.py](s23_schema.py) | Project reviewed observations onto existing fixed slots, retaining all extras. |

## 导出、页面与专项工具

| 文件 | 职责 |
| --- | --- |
| [build_bluff_inference.py](build_bluff_inference.py) | Validate semantic bluff assessments, bind them to facts, and build review artifacts. |
| [build_fixed_game_sample.py](build_fixed_game_sample.py) | Create the one-game example using the board's fixed night/day slots. |
| [build_name_contact_sheets.ps1](build_name_contact_sheets.ps1) | 辅助工具；仅对应专项任务时使用。 |
| [build_reviewed_weibo_roster_workbook.mjs](build_reviewed_weibo_roster_workbook.mjs) | 辅助工具；仅对应专项任务时使用。 |
| [build_s22_causal_review_report.py](build_s22_causal_review_report.py) | Publish the disposition of every original flag and the residual manual queue. |
| [build_s23_bluff_publication.py](build_s23_bluff_publication.py) | Build the public S23 bluff-review asset from formal game snapshots. |
| [build_s23_review.py](build_s23_review.py) | Assemble S23 AI candidates and a local human-review workspace; no DB import. |
| [build_season_media_review.py](build_season_media_review.py) | Build a linked media/text/frame review index and verify selected outputs. |
| [build_transcript_review.py](build_transcript_review.py) | Create a standalone, read-only HTML review page for transcript candidates. |
| [build_pending_slot_review.py](build_pending_slot_review.py) | 由2026-10-30剩余清单生成槽位复核页，保存备注并导出反馈，不写对局事实。 |
| [import_manual_slot_review.py](import_manual_slot_review.py) | 校验人工槽位反馈的来源、身份与修改前值，归档原JSON并生成S21/S23重建使用的复核sidecar；后续批次保留其他坐标和原批次依据；默认只检查，`--apply`写入。 |
| [build_weibo_name_review.py](build_weibo_name_review.py) | Join visual label readings to schedule photos and build offline review artifacts. |
| [capture_bilibili_frame.py](capture_bilibili_frame.py) | Capture selected original-video frames for game fact checking; no stream URLs logged. |
| [capture_s22_seat_frames.py](capture_s22_seat_frames.py) | Capture one source-video frame per game for visible seat-name labels. |
| [capture_season_speech_frames.py](capture_season_speech_frames.py) | Capture a late player-speech frame per source, preserving selection evidence. |
| [causal_voting_review.py](causal_voting_review.py) | Replay source-bound contextual reviews without claiming human verification. |
| [export_reviewed_weibo_roster.py](export_reviewed_weibo_roster.py) | Deduplicate human-reviewed schedule photo names with traceable corrections. |
| [export_s22_offline_review.py](export_s22_offline_review.py) | Build one portable HTML review file from disk; never connect to the database. |
| [import_bluff_feedback.py](import_bluff_feedback.py) | Validate exported review feedback; --apply stores it separately from source facts. |
| [import_s21_formal.py](import_s21_formal.py) | Build and atomically import formal S21 records from approved identity, phase and text evidence; audio is optional. |
| [inspect_s23_speech.py](inspect_s23_speech.py) | Locate numbered speech handoffs for AI inspection; no speaker facts imported. |
| [read_s22_frame_labels.py](read_s22_frame_labels.py) | Read S22 video-frame nameplates into seat-name-only review candidates. |
| [read_s23_screen.py](read_s23_screen.py) | Local OCR support for S23 candidate reviews; never changes game records. |
| [recover_bluff_feedback_text.py](recover_bluff_feedback_text.py) | Recover selected values and comments from a copied offline review page. |
