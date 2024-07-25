#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
import textwrap
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, cast

try:
    import srt
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "srt"],
        stdout=subprocess.DEVNULL,
    )
finally:
    # noinspection PyUnresolvedReferences
    import srt

Segment = tuple[str, str]


def filepath(value, strict=True):
    path = Path(value).resolve()
    assert path.is_file() if strict else path.suffix, "provided path is not a file"
    return path


def parse_args():
    prog = "condense"
    parser = argparse.ArgumentParser(
        prog=prog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Condense video to dialogue audio for passive immersion",
        epilog=textwrap.dedent(
            f"""
        examples:
          {prog} -i video.mkv out.mp3 # expects video.srt (or .ass/.ssa) to exist
          {prog} -i video.mp4 -s video_sub.srt out.acc
            """
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        dest="video",
        type=filepath,
        help="Path to video with format that ffmpeg supports",
    )
    parser.add_argument(
        "output",
        type=lambda v: filepath(v, False),
        help="Output path for condensed audio with format that ffmpeg supports",
    )
    parser.add_argument(
        "-s",
        "--subtitles",
        type=filepath,
        default=None,
        help="Path to subtitles file. Default to .srt/.ass/.ssa file with the same name as input video",
    )
    return parser.parse_args()


def call_ffmpeg(*args: str):
    return subprocess.check_call(
        ["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-nostats", "-y", *args],
        stdout=subprocess.DEVNULL,
    )


def format_timedelta(timedelta_timestamp: timedelta) -> str:
    return srt.timedelta_to_srt_timestamp(timedelta_timestamp).replace(",", ".")


def parse_srt(subtitles_path: Path) -> Iterable[Segment]:
    srt_path = subtitles_path.with_suffix(".srt")
    if subtitles_path.suffix != ".srt":
        call_ffmpeg("-i", str(subtitles_path), "-c:s", "srt", str(srt_path))

    subs = srt.parse(srt_path.read_text())
    for sub in srt.sort_and_reindex(subs):
        yield format_timedelta(sub.start), format_timedelta(sub.end)


def extract_segment(segment: Segment, index: int, audio_path: Path) -> Path:
    dest_path = audio_path.parent.joinpath(f"{index}{audio_path.suffix}")
    call_ffmpeg(
        "-i",
        str(audio_path),
        "-ss",
        segment[0],
        "-to",
        segment[1],
        "-c",
        "copy",
        str(dest_path),
    )
    return dest_path


def condense(segments: Iterable[Segment], video_path: Path, output_path: Path):
    with TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir).joinpath(video_path.stem + output_path.suffix)
        call_ffmpeg(
            "-i",
            str(video_path),
            "-map",
            "0:a",
            str(audio_path),
        )

        with Pool() as pool:
            segment_paths = pool.starmap(
                extract_segment,
                (
                    (segment, index, audio_path)
                    for index, segment in enumerate(segments)
                ),
            )

        filelist_path = Path(tmpdir).joinpath("filelist.txt")
        filelist_path.write_text("\n".join(f"file {path}" for path in segment_paths))
        call_ffmpeg(
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(filelist_path),
            "-c",
            "copy",
            str(output_path),
        )


def find_subtitles(video_path: Path) -> Path:
    valid_suffixes = [".srt", ".ass", ".ssa"]
    for suffix in valid_suffixes:
        subtitles_path = video_path.with_suffix(suffix)
        if subtitles_path.exists():
            return subtitles_path
    raise FileNotFoundError("no subtitles file found")


def main():
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError("ffmpeg executable not found")

    args = parse_args()
    video_path = cast(Path, args.video)
    output_path = cast(Path, args.output)
    subtitles_path = cast(Path, args.subtitles or find_subtitles(video_path))

    subtitles = parse_srt(subtitles_path)
    condense(
        subtitles,
        video_path,
        output_path,
    )


if __name__ == "__main__":
    main()
