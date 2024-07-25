# Immersion Condenser

Simple script that condense video to dialogue audio for passive immersion.
I made this because I couldn't find a condenser for Unix-like systems.

## Requirements

- `python3` somewhere in your PATH
- `ffmpeg` somewhere in your PATH
- `srt` module will be installed by the script, or you can run `pip install srt` first

## Install

```shell
curl -o ~/.local/bin/condense https://raw.githubusercontent.com/puzzlemoondev/immersion_condenser/main/condense.py && chmod +x ~/.local/bin/condense
```

Or clone the repo and run `make install`

## Usage

```
usage: condense [-h] -i VIDEO [-s SUBTITLES] output

Condense video to dialogue audio for passive immersion

positional arguments:
  output                Output path for condensed audio with format that
                        ffmpeg supports

options:
  -h, --help            show this help message and exit
  -i VIDEO, --input VIDEO
                        Path to video with format that ffmpeg supports
  -s SUBTITLES, --subtitles SUBTITLES
                        Path to subtitles file. Default to .srt/.ass/.ssa file
                        with the same name as input video

examples:
  condense -i video.mkv out.mp3 # expects video.srt (or .ass/.ssa) to exist
  condense -i video.mp4 -s video_sub.srt out.aac
```
