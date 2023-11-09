import json
import pprint
import subprocess
from pathlib import Path
from shutil import which, copy
from dataclasses import dataclass, asdict
from typing import Union, List

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
        duration = opentime.to_seconds(opentime.from_time_string(duration_timecode, fps))
    frames = 0
    if video_data.get('nb_frames', 0):
        frames = int(video_data.get('nb_frames', 0))
    elif duration and fps:
        frames = opentime.to_frames(opentime.from_seconds(duration, fps))
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
        'frames': frames
    }
    if video_data.get('width') and video_data.get('height'):
        res['resolution'] = (video_data.get('width'), video_data.get('height'))
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
    # pprint.pprint(shots_dicts)
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
        i = int(i + 1)
        if i < len(shot_starts):
            next_start_time, next_start_frame = shot_starts[i]
        else:
            next_start_time = opentime.to_seconds(opentime.from_frames(nb_frames, fps))
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


def export_shots(output_path: Union[Path, str], shot_list: List[ShotData]):
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    for shot_data in shot_list:
        if not shot_data.thumbnail or not shot_data.thumbnail.exists():
            shot_data.get_thumbnail()
        if not shot_data.movie or not shot_data.movie.exists():
            shot_data.get_movie()
        copy(shot_data.thumbnail, Path(output_path).joinpath(shot_data.thumbnail.name))
        copy(shot_data.movie, Path(output_path).joinpath(shot_data.movie.name))

