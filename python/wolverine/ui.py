
import sys
from pathlib import Path
from getpass import getuser
from json import loads, dumps
from typing import Union, List, Tuple, Dict

import mpv
from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from superqt import QLabeledRangeSlider, QLabeledSlider
from opentimelineio import opentime, schema

from wolverine import shots
from wolverine import utils
from wolverine.ui_utils import ONE_BILLION, ClickableSlider, ClickableRangeSlider, OTIOViewWidget

VALID_VIDEO_EXT = ['.mov', '.mp4', '.mkv', '.avi']
TEMP_SAVE_DIR = Path(f'c:/users/{getuser()}/Documents/Wolverine')


# TODO override opentimelineview's UI
#  - function to add : marker add, marker remove, ruler move, marker move, select shot
#  - override OTIOViewWidget and disable/hide what we don't need instead of recreating the whole class
#  - find a way to zoom in on specific parts of the timeline
#  - maybe split all external timeline files (otio, edl, etc...) into two timeline, one that corresponds to the
#     actual file, the other which is flattened by wolverine using (use otiotool.flatten_timeline) ?
# TODO add buttons `Add/remove Marker` which adds marker at current frame
# TODO update next/prev shots if a shot range is updated

# TODO export thumbnails, movies, edl, xml, otio, excel, audio of shots as wav/mp3
# TODO show video info in a widget (fps, frames, duration, resolution)
# TODO show shot info in a widget for the shot at the current frame (name, sequence, frame, timecode)

# TODO add parent sequence selection
# TODO add ignored shot option in UI

# TODO in shots panel, allow for a different shot start (other than 101)
# TODO run shot detection in background and update shots thumbnail/video in background
# TODO add progress bar
# TODO play shot movie when hovering over thumbnail or use existing player and ab-loop over shot range
#    use mpv command : self._player.command('ab-loop-a', shot_start_time); self._player.command('ab-loop-b', shot_end_time)
#    or set : self._player.ab_loop_a = shot_start_time; self._player.ab_loop_b = shot_end_time
#    or set : start/end and loop in mpv : self._player.start = shot_start_time; self._player.end = shot_end_time; self._player.loop = True
# TODO add colors to shots/shot markers
# TODO add unit tests

# FIXME keyboard shortcuts get overriden by dialog
# FIXME prev/next frame sometimes stuck between frames (haven't been able to reproduce this for a while)


class ShotWidget(QtWidgets.QWidget):

    def __init__(self, parent: QtWidgets.QWidget = None, shot_data: shots.ShotData = None):
        super().__init__(parent=parent)

        self._shot_data = shot_data
        self._build_ui()

    def _build_ui(self):
        self._shot_img_lb = QtWidgets.QLabel(self)
        if self._shot_data.thumbnail:
            self._shot_img_lb.setPixmap(QtGui.QIcon(self._shot_data.thumbnail.as_posix()).pixmap(80, 80))

        self._shot_name_lb = QtWidgets.QLabel(f'SH{(self._shot_data.index * 10):03d}')
        self._start_sp = QtWidgets.QSpinBox()
        self._start_sp.wheelEvent = lambda event: None
        self._start_sp.setRange(0, ONE_BILLION)
        self._start_sp.setValue(self._shot_data.start_frame)
        self._end_sp = QtWidgets.QSpinBox()
        self._end_sp.wheelEvent = lambda event: None
        self._end_sp.setRange(0, ONE_BILLION)
        self._end_sp.setValue(self._shot_data.end_frame)

        self._new_start_sp = QtWidgets.QSpinBox()
        self._new_start_sp.setRange(0, ONE_BILLION)
        self._new_start_sp.setValue(self._shot_data.new_start)
        self._new_start_sp.setEnabled(False)
        self._new_end_sp = QtWidgets.QSpinBox()
        self._new_end_sp.setRange(0, ONE_BILLION)
        self._new_end_sp.setValue(self._shot_data.new_end)
        self._new_end_sp.setEnabled(False)
        self._duration_sp = QtWidgets.QSpinBox()
        self._duration_sp.setRange(0, ONE_BILLION)
        self._duration_sp.setValue(self._shot_data.duration)
        self._duration_sp.setEnabled(False)

        range_lay = QtWidgets.QHBoxLayout()
        range_lay.addWidget(self._start_sp)
        range_lay.addWidget(self._end_sp)

        range_info_lay = QtWidgets.QHBoxLayout()
        range_info_lay.addWidget(self._new_start_sp)
        range_info_lay.addWidget(self._new_end_sp)
        range_info_lay.addWidget(self._duration_sp)

        data_lay = QtWidgets.QVBoxLayout()
        data_lay.addWidget(self._shot_name_lb)
        data_lay.addLayout(range_lay)
        data_lay.addLayout(range_info_lay)

        lay = QtWidgets.QHBoxLayout()
        lay.addWidget(self._shot_img_lb)
        lay.addLayout(data_lay)
        self.setLayout(lay)


class ShotListWidget(QtWidgets.QWidget):

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent=parent)

        self._shot_list = []
        self.shot_widgets = []
        self._build_ui()

    def _build_ui(self):
        self._shot_list_lw = QtWidgets.QWidget()
        cam_list_lay = QtWidgets.QVBoxLayout()
        self._shot_list_lw.setLayout(cam_list_lay)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidget(self._shot_list_lw)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._scroll)
        layout.setSpacing(0)
        layout.setMargin(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.setMinimumWidth(450)
        # self.setMaximumWidth(450)

    def refresh_shots(self, shot_list: List[shots.ShotData]):
        """
        Refresh list of camera widgets based on sequence/shots cameras

        Returns:
            list[CameraWidget]: list of camera widgets
        """
        self._shot_list = shot_list
        if not shot_list:
            return self.shot_widgets

        for shot_data in sorted(self._shot_list, key=lambda x: str(f'{x.index:06d}')):
            cam_widget = ShotWidget(parent=self, shot_data=shot_data)
            self.shot_widgets.append(cam_widget)
            self._shot_list_lw.layout().addWidget(cam_widget)
        self._shot_list_lw.layout().addItem(QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Minimum,
                                                                  QtWidgets.QSizePolicy.Expanding))
        return self.shot_widgets


class WolverineUI(QtWidgets.QDialog):

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent=parent)
        self.setWindowTitle('Wolverine - Sequence Splitter')

        self._full_screen: bool = False
        self._last_pause_state: bool = True
        self._probe_data: Union[utils.FFProbe, None] = None
        self.shots: List[shots.ShotData] = []

        self._build_ui()
        self._connect_ui()

        self._player = self.__init_player()
        self.load_config()

        # from fcpxml.fcp import FCPXML
        # fcp_path = Path(r'C:\Users\rlahmidi\Desktop\TFTSet10_ANC_Full_230728_shotnumbers.xml')
        # test = FCPXML(xml_file=fcp_path.as_posix())
        # print(test)
        #
        # from edl import EDLParser
        # edl_path = Path(r'C:\Users\rlahmidi\Desktop\TFTSet10_ANC_Full_230728_shotnumbers.edl')
        # test = EDLParser(fps=self._probe_data.fps)
        # test.parse(edl_path.read_text())
        # print(test)
        #
        # from opentimelineio.adapters import read_from_file
        # fcp = read_from_file(fcp_path)
        # edl = read_from_file(edl_path)
        # # edl_clips = edl.each_child()
        # edl_clip = list(edl.each_clip())
        # start, duration = edl_clip.source_range

        # self.installEventFilter(self)

    def _build_ui(self):
        self._src_file_le = QtWidgets.QLineEdit()
        self._src_file_le.setReadOnly(True)
        self._browse_src_pb = QtWidgets.QPushButton('Select Map File')
        self._threshold_sp = QtWidgets.QSpinBox()
        self._threshold_sp.wheelEvent = lambda event: None
        self._threshold_sp.setEnabled(False)
        self._threshold_sp.setRange(0, 100)
        self._threshold_sp.setValue(80)
        self._process_pb = QtWidgets.QPushButton('Process')
        self._process_pb.setEnabled(False)
        self._screen = QtWidgets.QFrame()
        self._screen.setMinimumSize(450, 450)
        self._loop_pb = QtWidgets.QPushButton('L')
        self._speed_sl = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
        self._speed_sl.setRange(1, 100)
        self._speed_sl.setValue(100)
        self._prev_shot_pb = QtWidgets.QPushButton('PS')
        self._prev_frame_pb = QtWidgets.QPushButton('PF')
        self._stop_pb = QtWidgets.QPushButton('S')
        self._pause_pb = QtWidgets.QPushButton('P')
        self._next_frame_pb = QtWidgets.QPushButton('NF')
        self._next_shot_pb = QtWidgets.QPushButton('NS')
        self._mute_pb = QtWidgets.QPushButton('M')
        self._volume_sl = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
        self._volume_sl.setRange(0, 100)
        self._volume_sl.setValue(100)
        self._fullscreen_pb = QtWidgets.QPushButton('F')
        self._timeline_sl = ClickableSlider(QtCore.Qt.Horizontal)
        self._timeline_sl.setEnabled(False)
        self._timeline_sl.setVisible(False)
        self._zoom_timeline_sl = QLabeledRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._zoom_timeline_sl.setEnabled(False)
        self._current_frame_sp = QtWidgets.QSpinBox()
        self._current_frame_sp.wheelEvent = lambda event: None
        self._current_frame_sp.setEnabled(False)
        self._marker_timeline_sl = ClickableRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._marker_timeline_sl.setEnabled(False)
        self._marker_timeline_sl.setVisible(False)
        self._otio_view = OTIOViewWidget(parent=self)
        self._dst_dir_le = QtWidgets.QLineEdit()
        self._browse_dst_pb = QtWidgets.QPushButton('Browse Destination')
        self._import_pb = QtWidgets.QPushButton('Import')
        self._export_pb = QtWidgets.QPushButton('Export')
        self._shots_panel_lw = ShotListWidget()

        self._player_controls_w = QtWidgets.QWidget()
        controls_lay = QtWidgets.QHBoxLayout()
        controls_lay.addWidget(self._loop_pb)
        controls_lay.addWidget(self._speed_sl)
        controls_lay.addWidget(self._prev_shot_pb)
        controls_lay.addWidget(self._prev_frame_pb)
        controls_lay.addWidget(self._stop_pb)
        controls_lay.addWidget(self._pause_pb)
        controls_lay.addWidget(self._next_frame_pb)
        controls_lay.addWidget(self._next_shot_pb)
        controls_lay.addWidget(self._mute_pb)
        controls_lay.addWidget(self._volume_sl)
        controls_lay.addWidget(self._fullscreen_pb)
        self._player_controls_w.setLayout(controls_lay)
        self._player_controls_w.setEnabled(False)

        screen_ctrl_lay = QtWidgets.QVBoxLayout()
        screen_ctrl_lay.addWidget(self._screen)
        screen_ctrl_lay.addWidget(self._player_controls_w)
        self._player_widget = QtWidgets.QWidget()
        player_widget_lay = QtWidgets.QHBoxLayout(self._player_widget)
        player_widget_lay.addLayout(screen_ctrl_lay)
        player_widget_lay.addItem(QtWidgets.QSpacerItem(10, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self._src_file_le, 0, 0, 1, 1)
        layout.addWidget(self._browse_src_pb, 0, 1, 1, 1)
        layout.addWidget(self._threshold_sp, 0, 2, 1, 1)
        layout.addWidget(self._process_pb, 0, 3, 1, 1)
        layout.addWidget(self._player_widget, 1, 0, 2, 4)
        layout.addWidget(self._timeline_sl, 3, 0, 1, 3)
        layout.addWidget(self._zoom_timeline_sl, 4, 0, 1, 3)
        layout.addWidget(self._current_frame_sp, 4, 3, 1, 1)
        layout.addWidget(self._marker_timeline_sl, 5, 0, 1, 3)
        layout.addWidget(self._shots_panel_lw, 1, 4, 6, 3)
        layout.addWidget(self._otio_view, 6, 0, 1, 4)
        layout.addWidget(self._dst_dir_le, 7, 0, 1, 4)
        layout.addWidget(self._browse_dst_pb, 7, 4, 1, 1)
        layout.addWidget(self._export_pb, 7, 5, 1, 1)
        layout.addWidget(self._import_pb, 7, 6, 1, 1)
        self.setLayout(layout)

    def _connect_ui(self):
        self._browse_src_pb.clicked.connect(self._browse_video)
        self._src_file_le.editingFinished.connect(self._video_selected)
        self._process_pb.clicked.connect(self._process_video)
        self._loop_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_L))
        self._speed_sl.valueChanged.connect(self._set_player_speed)
        self._prev_shot_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_P))
        self._prev_frame_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Left))
        self._stop_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_S))
        self._pause_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Space))
        self._next_frame_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Right))
        self._next_shot_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_N))
        self._mute_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_M))
        self._volume_sl.valueChanged.connect(self._set_player_volume)
        self._fullscreen_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_F))
        self._timeline_sl.sliderPressed.connect(lambda: self._pause_player(True))
        self._timeline_sl.sliderReleased.connect(self._timeline_seek)
        self._zoom_timeline_sl.sliderReleased.connect(lambda: self._update_timeline_focus())
        self._marker_timeline_sl.handleSelected.connect(self._timeline_seek)
        self._browse_dst_pb.clicked.connect(self._browse_output)
        self._export_pb.clicked.connect(self._export_all)

        # OTIOview signals
        self._otio_view.timeline_widget.selection_changed.connect(self._timeline_selection_changed)
        self._otio_view.time_slider_clicked.connect(self._timeline_seek)
        self._otio_view.ruler_pressed.connect(lambda: self._pause_player(True))
        self._otio_view.ruler_moved.connect(self._timeline_seek)
        self._otio_view.ruler_released.connect(self._timeline_seek)
        self._otio_view.marker_added.connect(lambda x: print('marker_added ==> ', x))
        self._otio_view.marker_removed.connect(lambda x: print('marker_removed ==> ', x))

    def eventFilter(self, source, event):
        # print('*'*50)
        # print('source ===> ', source)
        # print('event ===> ', event)
        # print('event.type() ===> ', event.type())
        if event.type() == QtCore.QEvent.Type.ShortcutOverride:
            return True
        if event.type() == QtCore.QEvent.KeyPress or event.type() == QtCore.QEvent.KeyRelease:
            print('KeyPress: %s [%r]' % (event.key(), source))
            self._player_controls(event.key())
            # event.ignore()
            return True

        return super(WolverineUI, self).eventFilter(source, event)

    def keyPressEvent(self, event):
        if event.key() in [QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return, QtCore.Qt.Key_Q]:
            return
        self._player_controls(event.key())
        # self.accept()

    def __init_player(self):
        # set mpv player and time observer callback
        player = mpv.MPV(wid=str(int(self._screen.winId())), keep_open='yes', framedrop='no')

        @player.property_observer('time-pos')
        def time_observer(_, value):
            self._time_observer(value)

        return player

    def _timeline_selection_changed(self, item):
        print('OTIO Selected Item : ', item)

    def _browse_video(self):
        last_source = Path(self._src_file_le.text())
        file_filter = f'Video files (*{" *".join(VALID_VIDEO_EXT)})'
        video_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose Source file', last_source.as_posix(),
                                                              file_filter)
        self._video_selected(video_path)

    def _video_selected(self, video_path: Union[str, Path] = None):
        video_path = video_path or self._src_file_le.text()
        if not video_path:
            return
        video_path = Path(video_path)
        if not video_path.exists():
            QtWidgets.QMessageBox.critical(self, 'File Selection Error', 'The file you have selected does not exist')
            return
        self._src_file_le.setText(video_path.as_posix())
        enable_ui = bool(self._src_file_le.text())
        self._process_pb.setEnabled(enable_ui)
        self._threshold_sp.setEnabled(enable_ui)

        self.save_config(video_path)
        self.load_temp_data(video_path)

    def load_temp_data(self, video_path: Path, save_path: Path = None):
        temp_save_path = save_path or TEMP_SAVE_DIR.joinpath(f'{video_path.stem}.json')
        if not temp_save_path.exists():
            return
        save_data = loads(temp_save_path.read_text())
        if int(save_data.get('threshold', 80)) != self._threshold_sp.value():
            return

        msg = 'A previous auto-save has been found, would you like to load it ?'
        msg_box = QtWidgets.QMessageBox.question(None, 'Load Auto-Save ?', msg)
        if msg_box == QtWidgets.QMessageBox.No:
            return
        self._process_video(save_data=save_data)

    def save_temp_data(self, video_path: Path, save_path: Path = None):
        wolverine_data = {
            'source': video_path.as_posix(),
            'threshold': self._threshold_sp.value(),
            'probe_data': self._probe_data.to_dict(),
            'shots': []
        }
        for shot in self.shots:
            wolverine_data['shots'].append(shot.to_dict())

        temp_save_path = save_path or TEMP_SAVE_DIR.joinpath(f'{video_path.stem}.json')
        temp_save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_save_path.write_text(dumps(wolverine_data))

    def load_config(self, save_path: Path = None):
        temp_save_path = save_path or TEMP_SAVE_DIR.joinpath(f'config.json')
        if not temp_save_path.exists():
            return

        last_open = loads(temp_save_path.read_text()).get('last_open', '')
        self._src_file_le.setText(Path(last_open).as_posix())

        if self._src_file_le.text():
            self.load_temp_data(Path(self._src_file_le.text()))

    def save_config(self, video_path: Path, save_path: Path = None):
        config_data = {'last_open': video_path.as_posix()}

        temp_save_path = save_path or TEMP_SAVE_DIR.joinpath(f'config.json')
        temp_save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_save_path.write_text(dumps(config_data))

    def _process_video(self, save_data: Dict = None):
        video_path = Path(self._src_file_le.text())
        if not self._player or not video_path.exists():
            return

        if not save_data:
            self._probe_data = utils.probe_file(video_path)
            self.shots = utils.probe_file_shots(video_path, self._probe_data.fps, self._probe_data.frames,
                                                detection_threshold=self._threshold_sp.value())
        else:
            self._probe_data = utils.FFProbe.from_dict(save_data['probe_data'])
            for shot_data in save_data.get('shots', []):
                shot_data = shots.ShotData.from_dict(shot_data)
                self.shots.append(shot_data)

        if not self.shots:
            QtWidgets.QMessageBox.critical(self, 'Detection Error', 'Could not detect any shots in provided video !')
            return

        self.save_temp_data(video_path)
        self._update_otio_timeline()

        frame_range = (1, self._probe_data.frames)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setRange(*frame_range)
        for slider in [self._timeline_sl, self._zoom_timeline_sl, self._marker_timeline_sl]:
            slider.blockSignals(True)
            slider.setTickInterval(1)
            slider.setRange(*frame_range)
        self._zoom_timeline_sl.setValue(frame_range)
        markers = [s.start_frame for s in self.shots]
        self._marker_timeline_sl.setValue(markers)
        self._shots_panel_lw.refresh_shots(self.shots)

        for slider in [self._current_frame_sp, self._timeline_sl, self._zoom_timeline_sl, self._marker_timeline_sl]:
            slider.setEnabled(True)
            slider.blockSignals(False)
        self._player_controls_w.setEnabled(True)

        self._player.loadfile(video_path.as_posix())
        self._player.pause = True

    def _update_otio_timeline(self, video_path: Path = None):
        video_path = video_path or Path(self._src_file_le.text())
        # add shots to OTIO track
        track = schema.Track(
            name=video_path.stem,
            kind=schema.TrackKind.Video
        )
        for shot in self.shots:
            track.append(shot.otio_clip)
        # add track to stack
        stack = schema.Stack(
            children=[track],
            name=video_path.stem,
        )
        # add stack to timeline
        timeline = schema.Timeline()
        timeline.tracks = stack
        timeline.metadata['source'] = video_path.as_posix()
        self._otio_view.load_timeline(timeline)
        self._otio_view.ruler.move_to_frame(self._current_frame_sp.value() or 1)

    def _browse_output(self):
        last_directory = Path(self._dst_dir_le.text())
        output_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Output Directory',
                                                                 last_directory.as_posix(),
                                                                 QtWidgets.QFileDialog.ShowDirsOnly)
        self._dst_dir_le.setText(output_path)

    def _export_all(self):
        if not self._dst_dir_le.text():
            QtWidgets.QMessageBox.critical(self, 'Output Error', 'No Output Directory Selected !')
            return
        utils.export_shots(self._dst_dir_le.text(), self.shots)

    def _update_timeline_focus(self, new_range: Tuple[int, int] = None):
        start, end = new_range or self._zoom_timeline_sl.value()
        markers = [s.start_frame for s in self.shots if s.start_frame >= start and s.end_frame <= end]
        current_frame = self._current_frame_sp.value()
        if not (start <= current_frame <= end):
            self._current_frame_sp.setValue(start if current_frame < start else end)
        self._timeline_sl.setRange(start, end)
        self._marker_timeline_sl.setValue(markers)
        self._marker_timeline_sl.setRange(start, end)

    def _time_observer(self, value: float):
        if not self._probe_data or not value:
            return
        current_frame = opentime.to_frames(opentime.from_seconds(value, self._probe_data.fps))
        self._timeline_sl.setValue(int(current_frame))
        self._current_frame_sp.setValue(int(current_frame))
        self._otio_view.ruler.move_to_frame(current_frame)
        QtWidgets.QApplication.processEvents()

    def _timeline_seek(self, value: Union[int, float] = None):
        if not self._probe_data:
            return
        value = value if isinstance(value, (int, float)) else self._timeline_sl.value()
        value_seconds = opentime.to_seconds(opentime.from_frames(value, self._probe_data.fps))
        self._player.seek(value_seconds, reference='absolute+exact')
        self._player.pause = self._last_pause_state

    def _pause_player(self, status: bool):
        self._last_pause_state = self._player.pause
        self._player.pause = status

    def _set_player_volume(self, volume: int):
        self._player.volume = volume

    def _set_player_speed(self, speed: int):
        self._player.speed = max(0.01, float(speed)/100.0)

    def _player_controls(self, key: QtCore.Qt.Key):
        if not self._player or not self._probe_data:
            return
        if key == QtCore.Qt.Key_Space:
            self._player.pause = not self._player.pause
        if key == QtCore.Qt.Key_S:
            self._pause_player(True)
            self._timeline_sl.setValue(0)
            self._timeline_seek(0.0)
        elif key == QtCore.Qt.Key_Left:
            self._player.frame_back_step()
        elif key == QtCore.Qt.Key_Right:
            self._player.frame_step()
        elif key == QtCore.Qt.Key_P:
            self._pause_player(True)
            current_frame = self._current_frame_sp.value()
            prev_start = max([f for f in self._marker_timeline_sl.value() if f < current_frame] or [0])
            self._timeline_sl.setValue(prev_start)
            self._timeline_seek(prev_start)
        elif key == QtCore.Qt.Key_N:
            self._pause_player(True)
            current_frame = self._current_frame_sp.value()
            next_start = min([f for f in self._marker_timeline_sl.value() if f > current_frame] or [0])
            self._timeline_sl.setValue(next_start)
            self._timeline_seek(next_start)
        elif key == QtCore.Qt.Key_M:
            self._player.mute = not self._player.mute
        elif key == QtCore.Qt.Key_L:
            self._player.loop = not self._player.loop
        elif key == QtCore.Qt.Key_F:
            if self._full_screen:
                # self._screen.showNormal()
                self.showNormal()
            else:
                self._screen.showFullScreen()
                self.showFullScreen()
            self._full_screen = not self._full_screen
            # self._player.fullscreen = not self._player.fullscreen  # not working


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ui = WolverineUI()
    ui.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
    ui.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
    ui.show()
    ui.raise_()

    sys.exit(app.exec_())


