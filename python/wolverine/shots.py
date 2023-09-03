import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from tempfile import mkdtemp

from opentimelineio import opentime
from opentimelineio.schema import Clip, Marker

from wolverine import log


@dataclass
class ShotData:
    index: int
    fps: float
    source: Path
    start_time: float
    duration_time: float
    start_frame: int
    duration: int = 0
    new_start: int = 101
    thumbnail: Path = None
    movie: Path = None
    is_ignored: bool = False
    _otio_clip: Clip = None

    def __post_init__(self):
        if not self.start_frame and self.start_time and self.fps:
            self.start_frame = opentime.to_frames(opentime.from_seconds(self.start_time, self.fps))
        if not self.start_time and self.start_frame and self.fps:
            self.start_time = opentime.to_seconds(opentime.from_frames(self.start_frame, self.fps))
        if not self.duration and self.duration_time and self.fps:
            self.duration = opentime.to_frames(opentime.from_seconds(self.duration, self.fps))
        if not self.duration_time and self.duration and self.fps:
            self.duration_time = opentime.to_seconds(opentime.from_frames(self.duration, self.fps))

        self.get_thumbnail()
        self.get_movie()

    @property
    def name(self):
        return f'SH{(self.index * 10):03d}'

    @property
    def end_frame(self):
        return self.start_frame + self.duration

    @property
    def new_end(self):
        return self.new_start + self.duration

    @property
    def otio_clip(self):
        if self._otio_clip:
            return self._otio_clip
        self._otio_clip = Clip()
        self._otio_clip.name = self.name
        self._otio_clip.source_range = opentime.TimeRange(
            start_time=opentime.from_frames(self.start_frame, self.fps),
            duration=opentime.from_frames(self.duration, self.fps),
        )
        # add marker at start
        otio_marker = Marker()
        otio_marker.marked_range = opentime.TimeRange(
            start_time=opentime.from_frames(self.start_frame, self.fps),
            duration=opentime.RationalTime()
        )
        self._otio_clip.markers.append(self.name)
        return self._otio_clip

    def get_thumbnail(self):
        thumb_out = Path(mkdtemp()).joinpath(f'{self.name}.jpg')
        start_time = opentime.to_time_string(opentime.from_frames(self.start_frame, self.fps))

        command_list = f'ffmpeg -i "{self.source.as_posix()}" -ss {start_time} -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -vf "thumbnail={self.start_frame}" -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'

        res = self._get_media(' '.join(command_list), thumb_out)
        self.movie = thumb_out if res else None

    def get_movie(self):
        shot_out = Path(mkdtemp()).joinpath(f'{self.name}{self.source.suffix}')
        start_time = opentime.to_time_string(opentime.from_frames(self.start_frame, self.fps))
        duration_time = opentime.to_time_string(opentime.from_frames(self.duration, self.fps))

        command_list = ['ffmpeg',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -t {duration_time}',
                        f'-c:v copy -c:a copy -vsync vfr {shot_out.as_posix()}']
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -ss {start_time} -vframes {self.duration} -vsync vfr {shot_out.as_posix()}'

        res = self._get_media(' '.join(command_list), shot_out)
        self.movie = shot_out if res else None

    def _get_media(self, command: str, output_path: Path) -> bool:
        if not self.source.exists() or self.source.stat().st_size == 0:
            log.critical('No source specified or source doesn\'t exist or is empty at : ({self.source})')
            return False

        log.debug(f'Running Movie Extract Command : {command}')
        err_msg = f'Could not extract media from file ({self.source.as_posix()})'
        try:
            subprocess.check_output(command, shell=True)
        except subprocess.CalledProcessError:
            log.critical()
            return False

        if not output_path.exists() or output_path.stat().st_size == 0:
            log.critical(err_msg)
        return True

    def as_dict(self):
        shot_data = asdict(self)
        del shot_data['otio_clip']
        shot_data['source'] = self.source.as_posix()
        return shot_data

    @staticmethod
    def from_dict(values):
        values['source'] = Path(values['source'])
        return ShotData(**values)
