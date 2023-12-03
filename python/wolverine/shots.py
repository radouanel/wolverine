from __future__ import annotations
import subprocess
from pathlib import Path
from tempfile import gettempdir
from dataclasses import dataclass, asdict
from typing import Any

from opentimelineio import opentime
from opentimelineio.schema import Clip, Marker, ExternalReference, Box2d, V2d, MissingReference

from wolverine import log


@dataclass
class ShotData:
    index: int
    fps: float
    source: Path
    range: opentime.TimeRange
    new_start: int = 101
    thumbnail: Path = None
    movie: Path = None
    audio: Path = None
    prefix: str = ''
    enabled: bool = True
    ignored: bool = False
    _otio_clip: Clip = None
    _update_otio: bool = False
    _save_dir: Path = None

    def __repr__(self) -> str:
        return (f'ShotData ({self.name}) [{self.start_frame}-{self.end_frame}] '
                f'-> [{self.new_start}-{self.new_end}][Dur:{self.duration}]')

    def __setattr__(self, __name: str, __value: Any) -> None:
        super().__setattr__(__name, __value)
        if __name.startswith('_') or __name in ['index']:
            return
        self._update_otio = True

    def __post_init__(self) -> None:
        if not self.thumbnail or not self.thumbnail.exists():
            self.generate_thumbnail()

    @property
    def name(self) -> str:
        prefix = '' if not self.prefix else f'{self.prefix.upper()}_'
        ignored = '' if not self.ignored else '_IGNORED'
        return f'{prefix}SH{self.index:03d}{ignored}'

    @property
    def start_frame(self) -> int:
        return self.range.start_time.to_frames()

    @start_frame.setter
    def start_frame(self, value: int) -> None:
        duration = (self.end_frame - value) + 1
        self.range = opentime.TimeRange(
            start_time=opentime.from_frames(value, self.fps),
            duration=opentime.from_frames(duration, self.fps),
        )

    @property
    def start_time(self) -> float:
        return self.range.start_time.to_seconds()

    @start_time.setter
    def start_time(self, value: float) -> None:
        self.start_frame = opentime.from_seconds(value, self.fps).to_frames()

    @property
    def duration(self) -> int:
        return self.range.duration.to_frames()

    @duration.setter
    def duration(self, value: int) -> None:
        self.range = opentime.TimeRange(
            start_time=self.range.start_time,
            duration=opentime.from_frames(value, self.fps),
        )

    @property
    def duration_time(self) -> float:
        return self.range.duration.to_seconds()

    @duration_time.setter
    def duration_time(self, value: float) -> None:
        self.range = opentime.TimeRange(
            start_time=self.range.start_time,
            duration=opentime.to_frames(opentime.from_seconds(value, self.fps)),
        )

    @property
    def end_frame(self) -> int:
        return self.range.end_time_inclusive().to_frames()

    @end_frame.setter
    def end_frame(self, value: int) -> None:
        self.range = opentime.range_from_start_end_time_inclusive(
            start_time=self.range.start_time,
            end_time_inclusive=opentime.from_frames(value, self.fps)
        )

    @property
    def end_time(self) -> float:
        return self.range.end_time_inclusive().to_seconds()

    @end_time.setter
    def end_time(self, value: float) -> None:
        self.range = opentime.range_from_start_end_time_inclusive(
            self.range.start_time,
            end_time_inclusive=opentime.to_frames(opentime.from_seconds(value, self.fps))
        )

    @property
    def new_end(self) -> int:
        new_range = opentime.TimeRange(
            start_time=opentime.from_frames(self.new_start, self.fps),
            duration=self.range.duration
        )
        return new_range.end_time_inclusive().to_frames()

    @new_end.setter
    def new_end(self, value: int) -> None:
        new_range = opentime.range_from_start_end_time_inclusive(
            start_time=opentime.from_frames(self.new_start, self.fps),
            end_time_inclusive=opentime.from_frames(value, self.fps)
        )
        self.duration = new_range.duration.to_frames()

    @property
    def new_end_time(self) -> float:
        return opentime.to_seconds(opentime.from_frames(self.end_frame, self.fps))

    @new_end_time.setter
    def new_end_time(self, value: float) -> None:
        new_range = opentime.range_from_start_end_time_inclusive(
            start_time=opentime.from_frames(self.new_start, self.fps),
            end_time_inclusive=opentime.to_frames(opentime.from_seconds(value, self.fps))
        )
        self.duration = new_range.duration.to_frames()

    @property
    def otio_clip(self) -> Clip:
        if self._otio_clip and not self._update_otio:
            return self._otio_clip
        self._otio_clip = Clip()
        self._otio_clip.name = self.name
        self._otio_clip.metadata['name'] = self.name
        self._otio_clip.source_range = self.range
        self._otio_clip.enabled = self.enabled and not self.ignored

        # add marker at start
        otio_marker = Marker(name=self.name)
        marker_range = opentime.TimeRange(
            start_time=opentime.from_frames(self.start_frame, self.fps),
            duration=opentime.RationalTime()
        )
        otio_marker.marked_range = marker_range
        self._otio_clip.markers.append(otio_marker)

        # add media references if any
        clip_box = None
        if self.thumbnail or self.movie:
            file_path = self.thumbnail or self.movie
            probe_cmd = (f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 '
                         f'"{file_path.as_posix()}"')
            try:
                resolution = subprocess.check_output(probe_cmd, shell=True)
            except subprocess.CalledProcessError as e:
                log.critical(f'Could not probe file ({file_path})')
                log.critical(e)
                resolution = None
            if resolution:
                width, height = (int(s) for s in str(resolution.decode()).split('x'))
                clip_box = Box2d(V2d(width, height))

        media_refs = {}
        if self.thumbnail:
            ref = ExternalReference(target_url=self.thumbnail.as_posix(), available_range=marker_range,
                                    available_image_bounds=clip_box)
            media_refs['thumbnail'] = ref
        if self.movie:
            ref = ExternalReference(target_url=self.movie.as_posix(), available_range=marker_range,
                                    available_image_bounds=clip_box)
            media_refs['reference'] = ref
        if media_refs:
            active_key = 'reference' if media_refs.get('reference') else 'thumbnail'
            # self._otio_clip.active_media_reference_key = active_key
            self._otio_clip.set_media_references(media_refs, active_key)
        else:
            self._otio_clip.media_reference = MissingReference()
        self._update_otio = False
        return self._otio_clip

    @property
    def save_directory(self) -> Path:
        if self._save_dir:
            return self._save_dir
        temp_dir = Path(gettempdir()).joinpath(f'wolverine/{self.source.stem}')
        if not temp_dir.exists():
            temp_dir.mkdir(parents=True)
        self._save_dir = temp_dir
        return self._save_dir

    @save_directory.setter
    def save_directory(self, value: str | Path) -> None:
        self._save_dir = Path(value)

    def generate_thumbnail(self) -> None:
        thumb_out = self.save_directory.joinpath(f'{self.name}.jpg')
        start_time = opentime.to_time_string(self.range.start_time)

        command_list = ['ffmpeg -hide_banner -loglevel error -y',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -vframes:v 1',
                        f'-fps_mode vfr "{thumb_out.as_posix()}"']
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -vf "thumbnail={self.start_frame}" -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'

        res = self._generate_media(' '.join(command_list), thumb_out)
        self.thumbnail = thumb_out if res else None

    def generate_movie(self) -> None:
        shot_out = self.save_directory.joinpath(f'{self.name}{self.source.suffix}')
        start_time = opentime.to_time_string(self.range.start_time)
        duration_time = opentime.to_time_string(self.range.duration)

        command_list = ['ffmpeg -hide_banner -loglevel error -y',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -t {duration_time}',
                        '-c:v copy -c:a copy -fps_mode vfr',
                        f'{shot_out.as_posix()}']
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -ss {start_time} -vframes {self.duration} -vsync vfr {shot_out.as_posix()}'

        res = self._generate_media(' '.join(command_list), shot_out)
        self.movie = shot_out if res else None

    def generate_audio(self) -> None:
        shot_out = self.save_directory.joinpath(f'{self.name}.wav')
        start_time = opentime.to_time_string(self.range.start_time)
        duration_time = opentime.to_time_string(self.range.duration)

        # https://superuser.com/questions/609740/extracting-wav-from-mp4-while-preserving-the-highest-possible-quality
        # ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 44100 -ac 2 output.wav
        command_list = ['ffmpeg -hide_banner -loglevel error -y',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -t {duration_time}',
                        '-vn -acodec pcm_s16le -ar 44100 -ac 2',
                        '-fps_mode vfr',
                        f'{shot_out.as_posix()}']

        res = self._generate_media(' '.join(command_list), shot_out)
        self.audio = shot_out if res else None

    def _generate_media(self, command: str, output_path: Path) -> bool:
        if not self.source.exists() or self.source.stat().st_size == 0:
            log.critical('No source specified or source doesn\'t exist or is empty at : ({self.source})')
            return False

        log.debug(f'Running Movie Extract Command : {command}')
        err_msg = f'Could not extract media from file ({self.source.as_posix()})'
        try:
            subprocess.check_output(command, shell=True)
        except subprocess.CalledProcessError:
            log.critical(err_msg)
            return False

        if not output_path.exists() or output_path.stat().st_size == 0:
            log.critical(err_msg)
        return True

    def to_dict(self) -> dict[str, Any]:
        def dict_factory(shot_data: list[tuple[str, Any]]):
            shot_dict = {}
            for k, v in shot_data:
                if k.startswith('_'):
                    continue
                if isinstance(v, Path):
                    v = v.as_posix()
                if isinstance(v, opentime.TimeRange):
                    v = {'start_time': v.start_time.to_frames(), 'duration': v.duration.to_frames()}
                shot_dict[k] = v
            return shot_dict

        return asdict(self, dict_factory=dict_factory)

    @staticmethod
    def from_dict(values: dict[str, Any]) -> ShotData:
        values['source'] = Path(values['source'])
        values['range'] = opentime.TimeRange(
            start_time=opentime.from_frames(values['range']['start_time'], values['fps']),
            duration=opentime.from_frames(values['range']['duration'], values['fps']),
        )
        if values.get('thumbnail'):
            values['thumbnail'] = Path(values['thumbnail'])
        if values.get('movie'):
            values['movie'] = Path(values['movie'])
        if values.get('audio'):
            values['audio'] = Path(values['audio'])
        return ShotData(**values)
