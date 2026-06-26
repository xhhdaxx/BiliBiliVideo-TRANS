#!/usr/bin/env python3
"""Bilibili m4s 合并工具（CLI 版）。

默认行为：扫描 input_folder/ 下所有 cid 子目录，合并到 output_video/<title>.mp4。
流程：strip 9 字节头 → ffprobe 识别流 → ffmpeg mux。
进度：解析 ffmpeg 的 -progress 输出，根据 videoInfo.json 的 duration 算百分比和 ETA。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

M4S_HEADER_SIZE = 9  # Bilibili m4s 前置的 ASCII "000000000" 垃圾头长度
ILLEGAL_NAME_CHARS = re.compile(r'[/\\:*?"<>|\r\n\t]')

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / "input_folder"
DEFAULT_OUTPUT = PROJECT_ROOT / "output_video"


def find_m4s_files(directory: Path) -> list[Path]:
    files = sorted(directory.glob("*.m4s"))
    if not files:
        raise FileNotFoundError(f"目录 {directory} 下未找到 .m4s 文件")
    return files


def strip_header(src: Path, dst: Path) -> None:
    """去掉 m4s 前 9 字节垃圾头后写出标准 fMP4。"""
    with src.open("rb") as f, dst.open("wb") as g:
        f.read(M4S_HEADER_SIZE)
        shutil.copyfileobj(f, g)


def probe_kind(path: Path) -> str:
    """用 ffprobe 取首路流的 codec_type（video / audio）。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "0",
         "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def read_meta(directory: Path) -> dict:
    """读 videoInfo.json，返回 {title, duration, status}。"""
    info = directory / "videoInfo.json"
    fallback = {"title": directory.name, "duration": None, "status": None}
    if not info.exists():
        return fallback
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback
    title = data.get("groupTitle") or data.get("title") or directory.name
    title = ILLEGAL_NAME_CHARS.sub("_", title).strip() or directory.name
    return {
        "title": title,
        "duration": data.get("duration"),
        "status": data.get("status"),
    }


def ensure_tools() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("错误：未找到 ffmpeg / ffprobe（macOS: brew install ffmpeg）")


def discover_targets(directory: Path) -> list[Path]:
    """目录本身含 *.m4s → [directory]；否则返回所有含 *.m4s 的子目录。"""
    if any(directory.glob("*.m4s")):
        return [directory]
    return sorted(d for d in directory.iterdir() if d.is_dir() and any(d.glob("*.m4s")))


def fmt_duration(seconds: float) -> str:
    """秒数 → 'M:SS' 或 'H:MM:SS'。"""
    s = int(max(0, seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_bar(progress: float, width: int = 24) -> str:
    filled = int(progress * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def run_ffmpeg_with_progress(cmd: list[str], duration: float | None, start: datetime) -> int:
    """跑 ffmpeg，逐行解析 -progress 输出刷新进度条。返回 returncode。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last_print = 0.0

    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line.startswith("out_time_ms="):
            if line.startswith("progress=end"):
                break
            continue
        if not duration:
            continue
        out_s = int(line.split("=", 1)[1]) / 1_000_000
        progress = min(out_s / duration, 1.0)
        elapsed = (datetime.now() - start).total_seconds()
        eta = (elapsed / progress - elapsed) if progress > 0.01 else 0
        speed = (out_s / elapsed) if elapsed > 0 else 0
        now = time.time()
        if now - last_print >= 0.1:
            sys.stdout.write(
                f"\r  {render_bar(progress)} {progress*100:5.1f}% | "
                f"{fmt_duration(out_s)}/{fmt_duration(duration)} | "
                f"剩余 {fmt_duration(eta)} | {speed:.0f}x   "
            )
            sys.stdout.flush()
            last_print = now

    rc = proc.wait()
    sys.stdout.write("\r" + " " * 100 + "\r")  # 回车 + 空格覆盖 + 回车
    if rc != 0:
        sys.stderr.write(proc.stderr.read() or "")
    return rc


def find_cover(directory: Path) -> Path | None:
    """优先用 image.jpg（单 P 封面），其次 group.jpg（合集封面）。"""
    for name in ("image.jpg", "group.jpg"):
        cover = directory / name
        if cover.exists() and cover.stat().st_size > 0:
            return cover
    return None


def merge_one(directory: Path, output: Path, keep_temp: bool, embed_cover: bool, verbose: bool) -> None:
    meta = read_meta(directory)
    duration = meta["duration"]

    if meta["status"] and meta["status"] != "completed":
        print(f"  ⚠ status={meta['status']}，源文件可能未完整下载")

    m4s_files = find_m4s_files(directory)
    temp_files: list[Path] = []
    video_path = audio_path = None

    for m4s in m4s_files:
        cleaned = m4s.with_suffix(".cleaned.mp4")
        strip_header(m4s, cleaned)
        temp_files.append(cleaned)
        kind = probe_kind(cleaned)
        if verbose:
            size_mb = m4s.stat().st_size / 1024 / 1024
            print(f"  {m4s.name}  ({size_mb:.1f} MB)  →  {kind}")
        if kind == "video" and video_path is None:
            video_path = cleaned
        elif kind == "audio" and audio_path is None:
            audio_path = cleaned

    if video_path is None:
        raise RuntimeError("未找到视频流")
    if audio_path is None:
        raise RuntimeError("未找到音频流")

    cover = find_cover(directory) if embed_cover else None
    if embed_cover:
        if cover:
            print(f"  封面: {cover.name}")
        else:
            print(f"  封面: 未找到 image.jpg/group.jpg，跳过嵌入")

    output.parent.mkdir(parents=True, exist_ok=True)
    # -i 顺序决定 -map 索引：0=视频，1=音频，2=封面（可选）
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path)]
    if cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map", "0:v", "-map", "1:a"]
    if cover:
        # 把封面作为第二个视频流附加进去，Quick Look / 访达缩略图会显示
        cmd += ["-map", "2", "-c", "copy", "-disposition:v:1", "attached_pic"]
    else:
        cmd += ["-c", "copy"]
    cmd += [
        "-movflags", "+faststart",
        "-progress", "pipe:1",   # 结构化进度走 stdout
        "-nostats",              # 抑制 stderr 的滚动统计行
        str(output),
    ]

    start = datetime.now()
    print(f"  开始时间: {start.strftime('%H:%M:%S')}")
    if verbose:
        print(f"  cmd: {' '.join(cmd)}")

    rc = run_ffmpeg_with_progress(cmd, duration, start)
    if rc != 0:
        if not keep_temp:
            for f in temp_files:
                f.unlink(missing_ok=True)
        raise subprocess.CalledProcessError(rc, cmd)

    end = datetime.now()
    elapsed = (end - start).total_seconds()
    print(f"  结束时间: {end.strftime('%H:%M:%S')}")
    print(f"  耗时: {fmt_duration(elapsed)}  →  {output.name}")

    if not keep_temp:
        for f in temp_files:
            f.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="merge.py",
        description="合并 Bilibili m4s 文件夹为 mp4（CLI）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 merge.py                                # 处理 input_folder/ 下所有 cid 目录\n"
            "  python3 merge.py input_folder/26060656533/      # 处理指定目录\n"
            "  python3 merge.py -o output_video/自定义.mp4     # 指定输出（仅单目标）\n"
            "  python3 merge.py -v --keep-temp                 # 详细日志 + 保留中间文件"
        ),
    )
    parser.add_argument("directory", type=Path, nargs="?", default=DEFAULT_INPUT,
                        help=f"输入目录（默认: {DEFAULT_INPUT.name}/）")
    parser.add_argument("-o", "--output", type=Path,
                        help="输出 mp4 路径（仅单目标时生效；默认 output_video/<title>.mp4）")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留 .cleaned.mp4 中间文件")
    parser.add_argument("--no-cover", action="store_true",
                        help="不嵌入封面（默认嵌入 image.jpg 作为 attached_pic，便于访达缩略图）")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="打印 ffprobe 结果与完整 ffmpeg 命令")
    args = parser.parse_args()

    ensure_tools()

    directory = args.directory.resolve()
    if not directory.is_dir():
        sys.exit(f"错误：{directory} 不是目录")

    targets = discover_targets(directory)
    if not targets:
        sys.exit(f"错误：{directory} 下未找到含 .m4s 的目录")

    print(f"发现 {len(targets)} 个待处理目录")
    overall_start = datetime.now()
    print(f"开始时间: {overall_start.strftime('%Y-%m-%d %H:%M:%S')}")

    errors: list[tuple[Path, str]] = []
    for i, target in enumerate(targets, 1):
        meta = read_meta(target)
        if args.output is not None and len(targets) == 1:
            output = args.output.resolve()
        else:
            output = DEFAULT_OUTPUT / f"{meta['title']}.mp4"
        print(f"\n[{i}/{len(targets)}] {target.name}  →  {output.relative_to(PROJECT_ROOT) if output.is_relative_to(PROJECT_ROOT) else output}")
        try:
            merge_one(target, output, args.keep_temp, not args.no_cover, args.verbose)
        except Exception as e:
            errors.append((target, str(e)))
            print(f"  失败: {e}")

    overall_end = datetime.now()
    print(f"\n{'=' * 50}")
    print(f"总计 {len(targets)} 个 | 成功 {len(targets) - len(errors)} | 失败 {len(errors)}")
    print(f"开始: {overall_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"结束: {overall_end.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"耗时: {fmt_duration((overall_end - overall_start).total_seconds())}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
