import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from tempfile import mkdtemp

from opentimelineio import opentime
from opentimelineio.schema import Clip, Marker, ExternalReference, Box2d, V2d, MissingReference

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
    enabled: bool = True
    _otio_clip: Clip = None
    _update_otio: bool = False

    def __post_init__(self):
        if not self.start_frame and self.start_time and self.fps:
            self.start_frame = opentime.to_frames(opentime.from_seconds(self.start_time, self.fps))
        if not self.start_time and self.start_frame and self.fps:
            self.start_time = opentime.to_seconds(opentime.from_frames(self.start_frame, self.fps))
        if not self.duration and self.duration_time and self.fps:
            self.duration = opentime.to_frames(opentime.from_seconds(self.duration, self.fps))
        if not self.duration_time and self.duration and self.fps:
            self.duration_time = opentime.to_seconds(opentime.from_frames(self.duration, self.fps))

        if not self.thumbnail:
            self.get_thumbnail()
        if not self.movie:
            self.get_movie()

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key.startswith('_') or key in ['index']:
            return
        self._update_otio = True

    @property
    def name(self):
        return f'SH{(self.index * 10):03d}'

    @property
    def end_frame(self):
        return self.start_frame + self.duration

    @end_frame.setter
    def end_frame(self, frame: int):
        self.duration = frame - self.start_frame

    @property
    def new_end(self):
        return self.new_start + self.duration

    @property
    def otio_clip(self):
        if self._otio_clip and not self._update_otio:
            return self._otio_clip
        self._otio_clip = Clip()
        self._otio_clip.name = self.name
        source_range = opentime.TimeRange(
            start_time=opentime.from_frames(self.start_frame, self.fps),
            duration=opentime.from_frames(self.duration, self.fps),
        )
        self._otio_clip.source_range = source_range
        self._otio_clip.enabled = self.enabled

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
            probe_cmd = f'ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "{file_path.as_posix()}"'
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

    def get_thumbnail(self):
        thumb_out = Path(mkdtemp()).joinpath(f'{self.name}.jpg')
        start_time = opentime.to_time_string(opentime.from_frames(self.start_frame, self.fps))

        command_list = ['ffmpeg -hide_banner -loglevel error',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -vframes:v 1',
                        f'-fps_mode vfr "{thumb_out.as_posix()}"']
        # command_list = f'ffmpeg -loglevel quiet -i "{self.source.as_posix()}" -vf "thumbnail={self.start_frame}" -vframes 1 -vsync vfr "{thumb_out.as_posix()}"'

        res = self._get_media(' '.join(command_list), thumb_out)
        self.thumbnail = thumb_out if res else None

    def get_movie(self):
        shot_out = Path(mkdtemp()).joinpath(f'{self.name}{self.source.suffix}')
        start_time = opentime.to_time_string(opentime.from_frames(self.start_frame, self.fps))
        duration_time = opentime.to_time_string(opentime.from_frames(self.duration, self.fps))

        command_list = ['ffmpeg -hide_banner -loglevel error',
                        f'-i "{self.source.as_posix()}"',
                        f'-ss {start_time} -t {duration_time}',
                        '-c:v copy -c:a copy -fps_mode vfr',
                        f'{shot_out.as_posix()}']
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
            log.critical(err_msg)
            return False

        if not output_path.exists() or output_path.stat().st_size == 0:
            log.critical(err_msg)
        return True

    def to_dict(self):
        def dict_factory(shot_data):
            return {k: v.as_posix() if isinstance(v, Path) else v
                    for k, v in shot_data
                    if not k.startswith('_')}

        return asdict(self, dict_factory=dict_factory)

    @staticmethod
    def from_dict(values):
        values['source'] = Path(values['source'])
        if values['thumbnail']:
            values['thumbnail'] = Path(values['thumbnail'])
        if values['movie']:
            values['movie'] = Path(values['movie'])
        return ShotData(**values)
