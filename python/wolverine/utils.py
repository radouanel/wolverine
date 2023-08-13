
import os
import re
import json
import pprint
import tempfile
import traceback
import subprocess
from shutil import which
from pathlib import Path
from dataclasses import dataclass

from wolverine import log


@dataclass
class FFProbe:
    index: int
    file: Path
    resolution: tuple
    fps: float
    duration: float
    frames: int


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
        out = subprocess.check_output(' '.join(command_list), shell=True, env=os.environ)
    except subprocess.CalledProcessError as e:
        log.critical(f'Could not probe file ({file_path})')
        log.critical(e)
        log.critical(traceback.format_exc())
        return
    out = json.loads(out)
    if print_stats:
        log.debug(f'Probing raw data for ({file_path.name}) returned :')
        pprint.pprint(out)

    video_data = [strm for strm in out.get('streams') if strm.get('codec_type') == 'video'
                  if strm.get('codec_name', '').lower() not in ['mjpeg', 'png', 'bmp', 'gif']]
    if video_data:
        video_data = video_data[0]
    else:
        video_data = {}
    extra_data = out.get('format', {})
    if video_data:
        fps = float(video_data.get('r_frame_rate').split('/')[0])/float(video_data.get('r_frame_rate').split('/')[1])
    else:
        fps = 0.0
    duration_timecode = extra_data.get('duration') or video_data.get('duration', 0) or video_data.get('tags', {}).get('DURATION', 0)
    duration = 0.0
    if duration_timecode and fps:
        duration = duration_to_seconds(duration_timecode)
    frames = 0
    if video_data.get('nb_frames', 0):
        frames = int(video_data.get('nb_frames', 0))
    elif duration and fps:
        frames = seconds_to_frames(duration, fps)
    if not duration and frames and fps:
        duration = frames / fps
    if not frames and fps and duration:
        frames = int((float(duration) / 60.0) * fps)
    res = {
        'index': video_data.get('index'),
        'file': file_path,
        'resolution': None,
        'fps': fps,
        'duration': duration,
        'frames': frames,
    }
    if video_data.get('width') and video_data.get('height'):
        res['resolution'] = (video_data.get('width'), video_data.get('height'))
    res = FFProbe(**res)
    if print_stats:
        log.debug(f'Probing parsed data for ({file_path.name}) is :')
        pprint.pprint(res)
    return res


def ffmpeg_shot_detection(file_path, threshold=14):
    file_path = Path(file_path)
    output_path = Path(tempfile.mktemp()).joinpath('shots.csv')
    output_path.parent.mkdir(exist_ok=True, parents=True)
    video_cmd = [
        'ffprobe -loglevel quiet -show_frames -of compact=p=0 -f lavfi',
        f'"movie={file_path.as_posix()},select=\'gt(scene\,{(float(threshold)/100)})\'"'
    ]
    log.debug(f'Running Shot Detection Command : {" ".join(video_cmd)}')
    try:
        out = subprocess.check_output(' '.join(video_cmd), shell=True, env=os.environ)
    except subprocess.CalledProcessError as e:
        log.critical(f'Could not probe file ({file_path})')
        log.critical(e)
        log.critical(traceback.format_exc())
        return
    return [dict([kv.split('=') for kv in f'media_type={line}'.split('|')])
            for line in str(out).strip().split('media_type=') if line and line != "b'"]


def frames_to_seconds(seconds, frame_rate):
    return seconds / frame_rate


def timecode_to_seconds(seconds, frame_rate):
    _zip_ft = zip((3600, 60, 1, 1 / frame_rate), seconds.split(':'))
    return sum(f * float(t) for f, t in _zip_ft)


def _seconds(value, frame_rate):
    # timecode/frame conversion courtesy of https://stackoverflow.com/a/34607115
    if isinstance(value, str):  # value seems to be a timestamp
        return timecode_to_seconds(value, frame_rate)
    elif isinstance(value, (int, float)):  # frames
        return frames_to_seconds(value, frame_rate)
    else:
        return 0


def seconds_to_timecode(seconds, frame_rate):
    seconds = float(seconds)
    return (f'{int(seconds / 3600):02d}:'
            f'{int(seconds / 60 % 60):02d}:'
            f'{int(seconds % 60):02d}:'
            f'{round((seconds - int(seconds)) * frame_rate):02d}')


def seconds_to_frames(seconds, frame_rate):
    return int(seconds * frame_rate)


def timecode_to_frames(timecode, frame_rate, start=None):
    return seconds_to_frames(_seconds(timecode, frame_rate) - _seconds(start, frame_rate), frame_rate)


def frames_to_timecode(frames, frame_rate, start=None):
    return seconds_to_timecode(_seconds(frames, frame_rate) + _seconds(start, frame_rate), frame_rate)


def duration_to_seconds(duration):
    """
    Converts an ffmpeg duration string into a decimal representing the number of seconds
    represented by the duration string; None if the string is not parsable.
    """
    pattern = r'^((((?P<hms_grp1>\d*):)?((?P<hms_grp2>\d*):)?((?P<hms_secs>\d+([.]\d*)?)))|' \
              '((?P<smu_value>\d+([.]\d*)?)(?P<smu_units>s|ms|us)))$'
    match = re.match(pattern, str(duration))
    if not match:
        return

    groups = match.groupdict()
    if groups['hms_secs'] is not None:
        value = float(groups['hms_secs'])
        if groups['hms_grp2'] is not None:
            value += int(groups['hms_grp1']) * 60 * 60 + int(groups['hms_grp2']) * 60
        elif groups['hms_grp1'] is not None:
            value += int(groups['hms_grp1']) * 60
    else:
        value = float(groups['smu_value'])
        units = groups['smu_units']
        if units == 'ms':
            value /= 1000.0
        elif units == 'us':
            value /= 1000000.0
    return value

