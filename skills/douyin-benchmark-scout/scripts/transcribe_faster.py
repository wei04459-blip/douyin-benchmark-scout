#!/usr/bin/env python3
"""Fast local transcription with faster-whisper, writing the standard transcript files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel

import run as scout


def timestamp(seconds: float, srt: bool = False) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model", default="base")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    run_dir = args.run.expanduser().resolve()
    config = scout.load_config(args.config)
    state = scout.load_state()
    rows = scout.load_rows(run_dir / "search", "search_contents_*.json")
    items = scout.filter_search_rows(
        rows,
        config,
        set(map(str, state.get("processed_aweme_ids", []))),
    )
    scout.attach_local_files(items, run_dir)
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, args.threads),
        num_workers=1,
    )

    available = [item for item in items if item.get("video_path") and Path(item["video_path"]).is_file()]
    print(f"快速本地转录：当前可用视频 {len(available)}/{len(items)}", flush=True)
    completed = 0
    for index, item in enumerate(items, 1):
        video_path = Path(item["video_path"]) if item.get("video_path") else None
        if not video_path or not video_path.is_file():
            continue
        aweme_id = str(item["aweme_id"])
        output_dir = run_dir / "transcripts" / aweme_id
        target_txt = output_dir / f"{aweme_id}.txt"
        target_json = output_dir / f"{aweme_id}.json"
        if target_txt.is_file() and target_json.is_file():
            completed += 1
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[快速转录 {index}/{len(items)}] {aweme_id}", flush=True)
        segments_iter, info = model.transcribe(
            str(video_path),
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=True,
        )
        segments = []
        for segment in segments_iter:
            text = str(segment.text or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "id": int(segment.id),
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                }
            )
        plain_text = "\n".join(segment["text"] for segment in segments).strip()
        target_txt.write_text(plain_text + ("\n" if plain_text else ""), encoding="utf-8")
        target_json.write_text(
            json.dumps(
                {
                    "text": plain_text,
                    "language": info.language,
                    "language_probability": info.language_probability,
                    "duration": info.duration,
                    "segments": segments,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        srt = []
        vtt = ["WEBVTT", ""]
        tsv = ["start\tend\ttext"]
        for number, segment in enumerate(segments, 1):
            srt.extend(
                [
                    str(number),
                    f"{timestamp(segment['start'], True)} --> {timestamp(segment['end'], True)}",
                    segment["text"],
                    "",
                ]
            )
            vtt.extend(
                [
                    f"{timestamp(segment['start'])} --> {timestamp(segment['end'])}",
                    segment["text"],
                    "",
                ]
            )
            tsv.append(
                f"{round(segment['start'] * 1000)}\t{round(segment['end'] * 1000)}\t{segment['text']}"
            )
        (output_dir / f"{aweme_id}.srt").write_text("\n".join(srt), encoding="utf-8")
        (output_dir / f"{aweme_id}.vtt").write_text("\n".join(vtt), encoding="utf-8")
        (output_dir / f"{aweme_id}.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
        completed += 1
        print(f"  完成：{len(segments)} 段，{round(info.duration)} 秒", flush=True)

    print(f"快速转录完成：{completed} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
