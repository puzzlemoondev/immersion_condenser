#!/usr/bin/env python3

import argparse
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field, replace
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, cast

Segment = tuple[str, str]

MUSIC_SYMBOLS = ("♬",)


@dataclass(order=True)
class Subtitle:
    index: int
    start: timedelta
    end: timedelta
    content: str = field(compare=False)
    proprietary: str = field(default_factory=str, compare=False)


# from https://github.com/cdown/srt
class SRT:
    RGX_TIMESTAMP_MAGNITUDE_DELIM = r"[,.:，．。：]"
    RGX_TIMESTAMP_FIELD = r"[0-9]+"
    RGX_TIMESTAMP_FIELD_OPTIONAL = r"[0-9]*"
    RGX_TIMESTAMP = "".join(
        [
            RGX_TIMESTAMP_MAGNITUDE_DELIM.join([RGX_TIMESTAMP_FIELD] * 3),
            RGX_TIMESTAMP_MAGNITUDE_DELIM,
            "?",
            RGX_TIMESTAMP_FIELD_OPTIONAL,
        ]
    )
    RGX_TIMESTAMP_PARSEABLE = r"^{}$".format(
        "".join(
            [
                RGX_TIMESTAMP_MAGNITUDE_DELIM.join(
                    ["(" + RGX_TIMESTAMP_FIELD + ")"] * 3
                ),
                RGX_TIMESTAMP_MAGNITUDE_DELIM,
                "?",
                "(",
                RGX_TIMESTAMP_FIELD_OPTIONAL,
                ")",
            ]
        )
    )
    RGX_INDEX = r"-?[0-9]+\.?[0-9]*"
    RGX_PROPRIETARY = r"[^\r\n]*"
    RGX_CONTENT = r".*?"
    RGX_POSSIBLE_CRLF = r"\r?\n"
    TS_REGEX = re.compile(RGX_TIMESTAMP_PARSEABLE)
    # noinspection RegExpUnnecessaryNonCapturingGroup
    SRT_REGEX = re.compile(
        r"\s*(?:({idx})\s*{eof})?({ts}) *-[ -] *> *({ts}) ?({proprietary})(?:{eof}|\Z)({content})"
        r"(?:{eof}|\Z)(?:{eof}|\Z|(?=(?:{idx}\s*{eof}{ts})))"
        r"(?=(?:(?:{idx}\s*{eof})?{ts}|\Z))".format(
            idx=RGX_INDEX,
            ts=RGX_TIMESTAMP,
            proprietary=RGX_PROPRIETARY,
            content=RGX_CONTENT,
            eof=RGX_POSSIBLE_CRLF,
        ),
        re.DOTALL,
    )

    SECONDS_IN_HOUR = 3600
    SECONDS_IN_MINUTE = 60
    HOURS_IN_DAY = 24
    MICROSECONDS_IN_MILLISECOND = 1000

    @classmethod
    def parse(cls, srt: str):
        expected_start = 0

        for match in cls.SRT_REGEX.finditer(srt):
            actual_start = match.start()
            cls._check_contiguity(srt, expected_start, actual_start)
            raw_index, raw_start, raw_end, proprietary, content = match.groups()

            content = content.replace("\r\n", "\n")

            try:
                raw_index = int(raw_index)
            except ValueError:
                raw_index = int(raw_index.split(".")[0])
            except TypeError:
                pass

            yield Subtitle(
                index=raw_index,
                start=cls.srt_timestamp_to_timedelta(raw_start),
                end=cls.srt_timestamp_to_timedelta(raw_end),
                content=content,
                proprietary=proprietary,
            )

            expected_start = match.end()

        cls._check_contiguity(srt, expected_start, len(srt))

    @classmethod
    def sort_and_reindex(
        cls, subtitles: Iterable[Subtitle], start_index=1, in_place=False, skip=True
    ):
        skipped_subs = 0
        # noinspection PyTypeChecker
        for sub_num, subtitle in enumerate(sorted(subtitles), start=start_index):
            if not in_place:
                subtitle = replace(subtitle)

            if skip:
                if (
                    not subtitle.content.strip()
                    or subtitle.start < timedelta(0)
                    or subtitle.start >= subtitle.end
                ):
                    skipped_subs += 1
                    continue

            subtitle.index = sub_num - skipped_subs

            yield subtitle

    @classmethod
    def srt_timestamp_to_timedelta(cls, timestamp: str):
        match = cls.TS_REGEX.match(timestamp)
        if match is None:
            raise RuntimeError(f"Unparseable timestamp: {timestamp}")
        hours, minutes, seconds, milliseconds = [
            int(m) if m else 0 for m in match.groups()
        ]
        return timedelta(
            hours=hours, minutes=minutes, seconds=seconds, milliseconds=milliseconds
        )

    @classmethod
    def timedelta_to_srt_timestamp(cls, timedelta_timestamp: timedelta):
        hours, seconds_remainder = divmod(
            timedelta_timestamp.seconds, cls.SECONDS_IN_HOUR
        )
        hours += timedelta_timestamp.days * cls.HOURS_IN_DAY
        minutes, seconds = divmod(seconds_remainder, cls.SECONDS_IN_MINUTE)
        milliseconds = (
            timedelta_timestamp.microseconds // cls.MICROSECONDS_IN_MILLISECOND
        )
        return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, milliseconds)

    @staticmethod
    def _check_contiguity(srt: str, expected_start: int, actual_start: int):
        if expected_start != actual_start:
            unmatched_content = srt[expected_start:actual_start]
            if expected_start == 0 and (
                unmatched_content.isspace() or unmatched_content == "\ufeff"
            ):
                return
            raise RuntimeError(f"unparseable SRT data: {unmatched_content}")


def filepath(value: str, strict=True):
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
          {prog} -i video.mp4 -s video_sub.srt out.aac
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
        type=Path,
        help="Output path for condensed audio with format that ffmpeg supports",
    )
    parser.add_argument(
        "-s",
        "--subtitles",
        type=filepath,
        default=None,
        help="Path to subtitles file. Default to .srt/.ass/.ssa file with the same name as input video",
    )
    parser.add_argument(
        "-f",
        "--filters",
        type=str,
        default="",
        help="Space separated words used to filter out subtitles",
    )
    parser.add_argument(
        "--skip-filter-music",
        action="store_true",
        help="Do not try filter out music subtitles",
    )
    return parser.parse_args()


def call_ffmpeg(*args: str):
    return subprocess.check_call(
        ["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-nostats", "-y", *args],
        stdout=subprocess.DEVNULL,
    )


def format_timedelta(timedelta_timestamp: timedelta) -> str:
    return SRT.timedelta_to_srt_timestamp(timedelta_timestamp).replace(",", ".")


def parse_srt(subtitles_path: Path, filters: set[str]) -> Iterable[Segment]:
    srt_path = subtitles_path.with_suffix(".srt")
    if subtitles_path.suffix != ".srt":
        call_ffmpeg("-i", str(subtitles_path), "-c:s", "srt", str(srt_path))

    subs = SRT.parse(srt_path.read_text())
    for sub in SRT.sort_and_reindex(subs):
        if filters and any(word in sub.content for word in filters):
            continue
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
    if output_path.is_dir():
        output_path = output_path.joinpath(video_path.with_suffix(".aac").name)
    subtitles_path = cast(Path, args.subtitles or find_subtitles(video_path))

    filters: set[str] = set()
    if args.filters:
        filters.update(word for word in args.filters.split(" ") if word)
    if not args.skip_filter_music:
        filters.update(MUSIC_SYMBOLS)

    subtitles = parse_srt(subtitles_path, filters)
    condense(
        subtitles,
        video_path,
        output_path,
    )


if __name__ == "__main__":
    main()
