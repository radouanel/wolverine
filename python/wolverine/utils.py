
import os
import re
import json
import pprint
import subprocess
from typing import List
from shutil import which
from pathlib import Path
from tempfile import mkdtemp
from dataclasses import dataclass

from wolverine import log


@dataclass
class ShotData:
    index: int
    fps: float
    source: Path
    start_time: float
    duration_time: float
    start_frame: int
    end_frame: int = 0
    duration: int = 0
    new_start: int = 101
    new_end: int = 0
    thumbnail: Path = None
    movie: Path = None

    def __post_init__(self):
        if not self.duration and self.duration_time:
            self.duration = seconds_to_frames(self.duration_time, self.fps)
        if not self.duration_time and self.duration:
            self.duration_time = frames_to_seconds(self.duration, self.fps)
        if not self.end_frame and self.start_frame and self.duration:
            self.end_frame = self.start_frame + self.duration
        if not self.new_end and self.new_start and self.duration:
            self.new_end = self.new_start + self.duration

        self.get_thumbnail()
        self.get_movie()

    def get_thumbnail(self):
        if not self.source.exists() or self.source.stat().st_size == 0:
            log.critical('No source specified or source doesn\'t exist or is empty at : ({self.source})')
            return
        thumb_out = Path(mkdtemp()).joinpath(f'SH{(self.index * 10):03d}.jpg')
        err_msg = f'Could not extract frame from file ({self.source.as_posix()})'

        start_time = frames_to_ffmpeg_timecode(self.start_frame, self.fps)
        command_list = f'ffmpeg -i "{self.source.as_posix()}" -ss {start_time} -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -vf "thumbnail={self.start_frame}" -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'
        log.debug(f'Running Thumbnail Command : {command_list}')
        try:
            subprocess.check_output(command_list, shell=True)
        except subprocess.CalledProcessError:
            log.critical(err_msg)
            return

        if not thumb_out.exists() or thumb_out.stat().st_size == 0:
            log.critical(err_msg)
        self.thumbnail = thumb_out

    def get_movie(self):
        if not self.source.exists() or self.source.stat().st_size == 0:
            log.critical('No source specified or source doesn\'t exist or is empty at : ({self.source})')
            return
        shot_out = Path(mkdtemp()).joinpath(f'SH{(self.index * 10):03d}{self.source.suffix}')
        start_time = frames_to_ffmpeg_timecode(self.start_frame, self.fps)
        duration_time = frames_to_ffmpeg_timecode(self.duration, self.fps)
        err_msg = f'Could not extract shot from file ({self.source.as_posix()})'
        command_list = ['ffmpeg',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -t {duration_time}',
                        f'-c:v copy -c:a copy -vsync vfr {shot_out.as_posix()}']
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -ss {start_time} -vframes {self.duration} -vsync vfr {shot_out.as_posix()}'
        log.debug(f'Running Movie Extract Command : {command_list}')
        try:
            # subprocess.check_output(' '.join(command_list), shell=True)
            subprocess.check_output(command_list, shell=True)
        except subprocess.CalledProcessError:
            log.critical(err_msg)
            return

        if not shot_out.exists() or shot_out.stat().st_size == 0:
            log.critical(err_msg)
        self.movie = shot_out


@dataclass
class FFProbe:
    index: int
    source: Path
    resolution: tuple
    fps: float
    duration: float
    frames: int
    shots: List[ShotData]


def probe_file(file_path, detection_threshold=20, print_stats=False):
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
        duration = ffmpeg_duration_to_seconds(duration_timecode)
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
        'source': file_path,
        'resolution': None,
        'fps': fps,
        'duration': duration,
        'frames': frames,
        'shots': []
    }
    if video_data.get('width') and video_data.get('height'):
        res['resolution'] = (video_data.get('width'), video_data.get('height'))
    shots_data = probe_file_shots(file_path, fps, frames, detection_threshold=detection_threshold)
    if shots_data:
        res['shots'] = shots_data
    res = FFProbe(**res)
    if print_stats:
        log.debug(f'Probing parsed data for ({file_path.name}) is :')
        pprint.pprint(res)
    return res


def probe_file_shots(file_path, fps, nb_frames, detection_threshold=20):
    file_path = Path(file_path)
    video_cmd = [
        'ffprobe -loglevel quiet -show_frames -of compact=p=0 -f lavfi',
        f'"movie={file_path.as_posix()},select=\'gt(scene\,{(float(detection_threshold)/100)})\'"'
    ]
    log.debug(f'Running Shot Detection Command : {" ".join(video_cmd)}')

    try:
        out = subprocess.check_output(' '.join(video_cmd), shell=True)
    except subprocess.CalledProcessError as e:
        log.critical(f'Could not probe file ({file_path})')
        log.critical(e)
        return

    shots_data = []
    shots_dicts = [dict([kv.split('=') for kv in f'media_type={line}'.split('|')])
                   for line in str(out).strip().split('media_type=') if line and line != "b'"]
    pprint.pprint(shots_dicts)
    shot_starts = []
    for shot_dict in shots_dicts:
        start_time = float(shot_dict.get('pkt_dts_time')
                           or shot_dict.get('pts_time')
                           or shot_dict.get('best_effort_timestamp_time')
                           or 0)
        start_frame = int(shot_dict.get('coded_picture_number')
                          or (shot_dict.get('pts', 0) / 1000)
                          or (shot_dict.get('best_effort_timestamp', 0) / 1000)
                          or 0)
        shot_starts.append((start_time, start_frame))
    for i, (start_time, start_frame) in enumerate(shot_starts):
        i = (i + 1)
        if i < len(shot_starts):
            next_start_time, next_start_frame = shot_starts[i]
        else:
            next_start_time = frames_to_seconds(nb_frames, fps)
            next_start_frame = nb_frames
        shot_data = ShotData(
            index=i,
            fps=fps,
            source=file_path,
            start_time=start_time,
            duration_time=(next_start_time - start_time),
            start_frame=start_frame,
            duration=(next_start_frame - start_frame),
        )
        shots_data.append(shot_data)
    return shots_data


def frames_to_seconds(frames, fps):
    return frames / fps


def timecode_to_seconds(seconds, fps):
    _zip_ft = zip((3600, 60, 1, 1 / fps), seconds.split(':'))
    return sum(f * float(t) for f, t in _zip_ft)


def _seconds(value, fps):
    # timecode/frame conversion courtesy of https://stackoverflow.com/a/34607115
    if isinstance(value, str):  # value seems to be a timestamp
        return timecode_to_seconds(value, fps)
    elif isinstance(value, (int, float)):  # frames
        return frames_to_seconds(value, fps)
    else:
        return 0


def seconds_to_timecode(seconds, fps):
    seconds = float(seconds)
    return (f'{int(seconds / 3600):02d}:'
            f'{int(seconds / 60 % 60):02d}:'
            f'{int(seconds % 60):02d}:'
            f'{round((seconds - int(seconds)) * fps):02d}')


def seconds_to_ffmpeg_timecode(seconds):
    if seconds < 60.0:
        return "00:00:" + '{:05.2f}'.format(seconds)
    else:
        milliseconds = seconds - float(int(seconds))
        total_seconds = int(seconds - milliseconds)
        seconds = total_seconds % 60
        total_minutes = int((total_seconds - seconds)/60.0)
        minutes = int(total_minutes % 60.0)
        hours = int((total_minutes-minutes)/60.0)
        return "%s:%s:%s" % ('{:02}'.format(hours), '{:02}'.format(hours), '{:05.2f}'.format(seconds + milliseconds))


def seconds_to_frames(seconds, fps):
    return int(float(seconds) * float(fps))


def timecode_to_frames(timecode, fps, start=None):
    return seconds_to_frames(_seconds(timecode, fps) - _seconds(start, fps), fps)


def frames_to_timecode(frames, fps, start=None):
    seconds = _seconds(frames, fps) + _seconds(start, fps)
    return seconds_to_timecode(seconds, fps)


def frames_to_ffmpeg_timecode(frames, fps, start=None):
    seconds = _seconds(frames, fps) + _seconds(start, fps)
    return seconds_to_ffmpeg_timecode(seconds)


def ffmpeg_duration_to_seconds(duration):
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

