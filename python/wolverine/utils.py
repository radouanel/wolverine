from __future__ import annotations

import json
import pprint
import subprocess
from pathlib import Path
from shutil import which
from dataclasses import dataclass, asdict
from typing import Iterator

from opentimelineio import opentime

from wolverine import log
from wolverine.shots import ShotData


@dataclass
class FFProbe:
    index: int
    source: Path
    resolution: tuple
    fps: float
    duration: float
    frames: int

    def to_dict(self):
        probe = asdict(self)
        probe['source'] = self.source.as_posix()

        return probe

    @staticmethod
    def from_dict(values):
        values['source'] = Path(values['source'])
        return FFProbe(**values)


def probe_file(file_path, print_stats=False):
    file_path = Path(file_path)
    ffprobe_path = 'ffprobe'
    if not which('ffprobe'):
        raise IOError('No ffprobe binary found in env !')

    command_list = [
            ffprobe_path,
            '-v', 'error',
            '-print_format', 'json',
            '-hide_banner',
            '-show_error',
            '-show_format',
            '-show_streams',
            '-show_programs',
            '-show_chapters',
            '-show_private_data',
            f'"{file_path.as_posix()}"'
    ]
    log.debug(f'PROBING ({file_path.name}): [{" ".join(command_list)}]')
    try:
        out = subprocess.check_output(' '.join(command_list), shell=True)
    except subprocess.CalledProcessError as e:
        log.critical(f'Could not probe file ({file_path})')
        log.critical(e)
        return

    out = json.loads(out)
    if print_stats:
        log.debug(f'Probing raw data for ({file_path.name}) returned :')
        log.debug(pprint.pprint(out))
    # parse data and video streams
    video_data = [strm for strm in out.get('streams') if strm.get('codec_type') == 'video'
                  if strm.get('codec_name', '').lower() not in ['mjpeg', 'png', 'bmp', 'gif']]
    if video_data:
        video_data = video_data[0]
    else:
        video_data = {}
    extra_data = out.get('format', {})
    # determine fps
    if video_data:
        fps = float(video_data.get('r_frame_rate').split('/')[0])/float(video_data.get('r_frame_rate').split('/')[1])
    else:
        fps = 0.0
    # determine duration
    duration_timecode = extra_data.get('duration') or video_data.get('duration', 0) or video_data.get('tags', {}).get('DURATION', 0)
    duration = 0.0
    if duration_timecode and fps:
        duration = opentime.to_seconds(opentime.from_time_string(duration_timecode, fps))
    # determine number of frames
    frames = 0
    if video_data.get('nb_frames', 0):
        frames = int(video_data.get('nb_frames', 0))
    elif duration and fps:
        frames = opentime.to_frames(opentime.from_seconds(duration, fps))
    if not duration and frames and fps:
        duration = frames / fps
    if not frames and fps and duration:
        frames = int((float(duration) / 60.0) * fps)
    # determine resolution
    resolution = None
    if video_data.get('width') and video_data.get('height'):
        resolution = (video_data.get('width'), video_data.get('height'))
    # construct FFProbe dataclass
    res = {
        'index': video_data.get('index'),
        'source': file_path,
        'resolution': resolution,
        'fps': fps,
        'duration': duration,
        'frames': frames
    }
    if print_stats:
        log.debug(f'Parsed data for ({file_path.name}) is :')
        pprint.pprint(res)
    res = FFProbe(**res)
    return res


def probe_file_shots(file_path: str | Path, fps: float, nb_frames: int, detection_threshold: int = 20) -> Iterator[ShotData]:
    file_path = Path(file_path)
    clean_path = file_path.as_posix().replace(':', '\\\\:')
    video_cmd = [
        'ffprobe -loglevel quiet -show_frames -of compact=p=0 -f lavfi',
        f'"movie={clean_path},select=\'gt(scene\,{(float(detection_threshold)/100)})\'"'
    ]
    log.debug(f'Running Shot Detection Command : {" ".join(video_cmd)}')

    try:
        out = subprocess.check_output(' '.join(video_cmd), shell=True)
    except subprocess.CalledProcessError as e:
        log.critical(f'Could not probe file ({file_path})')
        log.critical(e)
        yield 0
        return

    shots_dicts = [dict([kv.split('=') for kv in f'media_type={line}'.split('|')])
                   for line in str(out).strip().split('media_type=') if line and line != "b'"]
    shot_starts = [0]
    for shot_dict in shots_dicts:
        start_time = float(shot_dict.get('pkt_dts_time')
                           or shot_dict.get('pts_time')
                           or shot_dict.get('best_effort_timestamp_time')
                           or 0)
        start_frame = int((int(shot_dict.get('pts', 1)) / 1000)
                          or (int(shot_dict.get('best_effort_timestamp', 1)) / 1000)
                          or shot_dict.get('coded_picture_number')
                          or 0)
        if not start_frame and start_time:
            start_frame = opentime.from_seconds(start_time, fps).to_frames()
        shot_starts.append(start_frame)

    shots_starts = sorted(set(shot_starts))
    yield len(shots_starts)

    for i, start_frame in enumerate(shots_starts):
        i += 1
        if i < len(shot_starts):
            next_start_frame = shot_starts[i] - 1
        else:
            next_start_frame = nb_frames
        shot_data = ShotData(
            index=(i * 10),
            fps=fps,
            source=file_path,
            range=opentime.range_from_start_end_time_inclusive(
                start_time=opentime.from_frames(start_frame, fps),
                end_time_inclusive=opentime.from_frames(next_start_frame, fps),
            )
        )
        yield shot_data

