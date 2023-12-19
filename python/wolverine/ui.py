from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from json import loads, dumps
from typing import Union, List, Tuple, Dict, Callable

import mpv
from superqt import QLabeledRangeSlider, QLabeledSlider
from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from opentimelineio import opentime, schema, adapters

from wolverine import log
from wolverine import shots
from wolverine import utils
from wolverine.ui_utils import ONE_BILLION, OTIOViewWidget

VALID_VIDEO_EXT = ['.mov', '.mp4', '.mkv', '.avi']
TEMP_SAVE_DIR = Path(os.getenv('WOLVERINE_PREFS_PATH', Path.home())).joinpath('wolverine')


# FIXME current frame spinbox and otio ruler sometimes don't have same value
# FIXME issue with path containig ":" Ex: R:/SYNDRA
# TODO add log file
# TODO make sur shots aren't duplicated

# TODO add progress bar
# TODO add icons to player buttons
# TODO test with an actual edit file and check if metadata is still present when re-exported from premiere/afterfx
# TODO add .otio/.edl/.xml import option as well

# TODO override opentimelineview's UI
#  - find a way to zoom in on specific parts of the timeline
#  - maybe split all external timeline files (otio, edl, etc...) into two timeline, one that corresponds to the
#     actual file, the other which is flattened by wolverine using (use otiotool.flatten_timeline) ?
#  - prevent timeline from resetting zoom everytime it is updated

# TODO enable add marker button only if current frame doesn't already have a marker
# TODO enable remove marker button only if current frame has a marker
# TODO show video info in a widget (fps, frames, duration, resolution)
# TODO add parent sequence selection and add clips representing sequences with different colors (add toggle sequences in timeline button too)
# TODO add framerate selection and use (is_valid_timecode_rate and nearest_valid_timecode_rate) to check/get correct fps
# TODO use opentime.rescaled_to to get correct ranges when fps from movie != fps in UI
# TODO when playing select current shot in shots list, when clicking shot junp to shot start in timeline, when double clicking shot ab-loop over it

# TODO update current basic export actions system (make more workable with other UIs and progress bar and export action selection widget)
# TODO run shot detection in background and update shots thumbnail/video in background
# TODO add ab-loop over range in player
#    use mpv command : self._player.command('ab-loop-a', shot_start_time); self._player.command('ab-loop-b', shot_end_time)
#    or set : self._player.ab_loop_a = shot_start_time; self._player.ab_loop_b = shot_end_time
#    or set : start/end and loop in mpv : self._player.start = shot_start_time; self._player.end = shot_end_time; self._player.loop = True

# FIXME keyboard shortcuts get overriden by dialog (make don't use QDialog)
# TODO add unit tests

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


@dataclass
class ExportAction:
    description: str
    func: Callable


class ShotWidget(QtWidgets.QFrame):
    sig_range_changed = QtCore.Signal(shots.ShotData, tuple)
    sig_shot_changed = QtCore.Signal()
    sig_shot_deleted = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget = None, shot_data: shots.ShotData = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName('ShotWidget')

        self._shot_data: shots.ShotData = shot_data
        self.__updating_ui: bool = False

        self._build_ui()
        self.fill_values_from(self._shot_data)
        self._connect_ui()

    def _build_ui(self) -> None:
        self._shot_img_lb = QtWidgets.QLabel(self)
        if self._shot_data.thumbnail:
            self._shot_img_lb.setPixmap(QtGui.QIcon(self._shot_data.thumbnail.as_posix()).pixmap(80, 80))

        self._shot_name_lb = QtWidgets.QLabel(self._shot_data.name)
        self._shot_enabled_cb = QtWidgets.QCheckBox('Enabled')
        self._shot_enabled_cb.setChecked(self._shot_data.enabled)
        self._shot_ignored_cb = QtWidgets.QCheckBox('Ignored')
        self._shot_ignored_cb.setChecked(self._shot_data.ignored)
        self._shot_delete_pb = QtWidgets.QPushButton('Delete')
        self._start_sp = QtWidgets.QSpinBox()
        self._end_sp = QtWidgets.QSpinBox()

        self._new_start_sp = QtWidgets.QSpinBox()
        self._duration_sp = QtWidgets.QSpinBox()
        self._new_end_sp = QtWidgets.QSpinBox()

        for widget in [self._start_sp, self._end_sp, self._duration_sp, self._new_start_sp, self._new_end_sp]:
            widget.wheelEvent = lambda event: None
            widget.setRange(0, ONE_BILLION)
        # self._start_sp.setRange(1, ONE_BILLION)
        self._end_sp.setRange(1, ONE_BILLION)

        header_lay = QtWidgets.QHBoxLayout()
        header_lay.addWidget(self._shot_name_lb)
        header_lay.addWidget(self._shot_enabled_cb)
        header_lay.addWidget(self._shot_ignored_cb)
        header_lay.addWidget(self._shot_delete_pb)

        range_lay = QtWidgets.QHBoxLayout()
        range_lay.addWidget(QtWidgets.QLabel('S'))
        range_lay.addWidget(self._start_sp)
        range_lay.addWidget(QtWidgets.QLabel('E'))
        range_lay.addWidget(self._end_sp)

        range_info_lay = QtWidgets.QHBoxLayout()
        range_info_lay.addWidget(QtWidgets.QLabel('NS'))
        range_info_lay.addWidget(self._new_start_sp)
        range_info_lay.addWidget(QtWidgets.QLabel('D'))
        range_info_lay.addWidget(self._duration_sp)
        range_info_lay.addWidget(QtWidgets.QLabel('NE'))
        range_info_lay.addWidget(self._new_end_sp)

        data_lay = QtWidgets.QVBoxLayout()
        data_lay.addLayout(header_lay)
        data_lay.addLayout(range_lay)
        data_lay.addLayout(range_info_lay)

        lay = QtWidgets.QHBoxLayout()
        lay.addWidget(self._shot_img_lb)
        lay.addLayout(data_lay)
        self.setLayout(lay)

        self.setStyleSheet('#ShotWidget {border: 1px solid black;}')

    def _connect_ui(self) -> None:
        self._shot_enabled_cb.stateChanged.connect(self._toggle_enabled)
        self._shot_ignored_cb.stateChanged.connect(self._toggle_ignored)
        self._shot_delete_pb.clicked.connect(lambda: self.sig_shot_deleted.emit(self._shot_data.start_frame))
        self._start_sp.editingFinished.connect(lambda: self._range_changed('start'))
        self._end_sp.editingFinished.connect(lambda: self._range_changed('end'))
        self._duration_sp.editingFinished.connect(lambda: self._range_changed('duration'))
        self._new_start_sp.editingFinished.connect(lambda: self._range_changed('new_start'))
        self._new_end_sp.editingFinished.connect(lambda: self._range_changed('new_end'))

    def fill_values_from(self, shot_data: shots.ShotData | None = None):
        shot_data = shot_data or self._shot_data

        self.__updating_ui = True
        self._start_sp.setValue(shot_data.start_frame)
        self._end_sp.setValue(shot_data.end_frame)
        self._new_start_sp.setValue(shot_data.new_start)
        self._duration_sp.setValue(shot_data.duration)
        self._new_end_sp.setValue(shot_data.new_end)
        self.__updating_ui = False

    def _toggle_enabled(self):
        self._shot_data.enabled = self._shot_enabled_cb.isChecked()
        self.sig_shot_changed.emit()

    def _toggle_ignored(self):
        self._shot_data.ignored = self._shot_ignored_cb.isChecked()
        self.sig_shot_changed.emit()

    def _range_changed(self, op: str) -> None:
        if self.__updating_ui:
            return
        prev_range = (self._shot_data.start_frame, self._shot_data.end_frame)
        current_range = opentime.TimeRange(
            start_time=self._shot_data.range.start_time,
            duration=self._shot_data.range.duration
        )
        if op == 'start':
            self._shot_data.start_frame = self._start_sp.value()
        if op == 'end':
            self._shot_data.end_frame = self._end_sp.value()
        if op == 'duration':
            self._shot_data.duration = self._duration_sp.value()
        if op == 'new_start':
            self._shot_data.new_start = self._new_start_sp.value()
        if op == 'new_end':
            self._shot_data.new_end = self._new_end_sp.value()

        up_to_date = (self._shot_data.range == self._shot_data.range)
        self._shot_name_lb.setText(('[*]' if not up_to_date else '') + self._shot_data.name)

        if self._shot_data.range == current_range:
            return

        self.fill_values_from()
        self._shot_data.generate_thumbnail()
        self.sig_range_changed.emit(self._shot_data, prev_range)


class ShotListWidget(QtWidgets.QWidget):
    sig_shot_range_changed = QtCore.Signal(shots.ShotData, tuple)
    sig_shots_changed = QtCore.Signal()
    sig_shot_deleted = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent=parent)

        self._shot_list = []
        self.shot_widgets = []
        self._build_ui()
        self._connect_ui()

    def _build_ui(self):
        self._shots_prefix_le = QtWidgets.QLineEdit()

        self._shots_start_sp = QtWidgets.QSpinBox()
        self._shots_start_sp.wheelEvent = lambda event: None
        self._shots_start_sp.setRange(0, ONE_BILLION)
        self._shots_start_sp.setValue(101)

        self._shot_list_lw = QtWidgets.QWidget()
        self._shot_list_lw.setLayout(QtWidgets.QVBoxLayout())

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidget(self._shot_list_lw)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        prefix_lay = QtWidgets.QHBoxLayout()
        prefix_lay.addWidget(QtWidgets.QLabel('Shots Prefix :'))
        prefix_lay.addWidget(self._shots_prefix_le)

        starts_lay = QtWidgets.QHBoxLayout()
        starts_lay.addWidget(QtWidgets.QLabel('Shots Start :'))
        starts_lay.addWidget(self._shots_start_sp)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(prefix_lay)
        layout.addLayout(starts_lay)
        layout.addWidget(self._scroll)
        layout.setSpacing(0)
        layout.setMargin(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.setMinimumWidth(450)

    def _connect_ui(self):
        self._shots_prefix_le.editingFinished.connect(self._update_shot_names)
        self._shots_start_sp.valueChanged.connect(self._update_shots_start)

    @property
    def prefix(self) -> str:
        return self._shots_prefix_le.text()

    @prefix.setter
    def prefix(self, value: str) -> None:
        self._shots_prefix_le.setText(value)

    @property
    def start(self) -> int:
        return self._shots_start_sp.value()

    @start.setter
    def start(self, value: int) -> None:
        self._shots_start_sp.setValue(value)

    def _update_shot_names(self):
        if not self._shot_list:
            return
        prefix = self._shots_prefix_le.text()
        shots_changed = False
        for shot_data in self._shot_list:
            if shot_data.prefix == prefix:
                continue
            shot_data.prefix = prefix
            shots_changed = True
        if shots_changed:
            self.sig_shots_changed.emit()

    def _update_shots_start(self, new_start: int):
        if not self._shot_list:
            return
        shots_changed = False
        for shot_data in self._shot_list:
            if shot_data.new_start == new_start:
                continue
            shot_data.new_start = new_start
            shots_changed = True
        if shots_changed:
            self.sig_shots_changed.emit()

    def refresh_shots(self, shot_list: List[shots.ShotData]):
        """
        Refresh list of camera widgets based on sequence/shots cameras

        Returns:
            list[CameraWidget]: list of camera widgets
        """
        self._shot_list = shot_list
        if not shot_list:
            return self.shot_widgets

        while self._shot_list_lw.layout().count():
            child = self._shot_list_lw.layout().takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for shot_data in sorted(self._shot_list, key=lambda x: str(f'{x.index:06d}')):
            shot_widget = ShotWidget(parent=self, shot_data=shot_data)
            shot_widget.sig_range_changed.connect(self.sig_shot_range_changed)
            shot_widget.sig_shot_changed.connect(self.sig_shots_changed)
            shot_widget.sig_shot_deleted.connect(self.sig_shot_deleted)
            self.shot_widgets.append(shot_widget)
            self._shot_list_lw.layout().addWidget(shot_widget)
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
        self.timeline = None
        self._export_actions: list[ExportAction] = []

        self._build_ui()
        self._connect_ui()

        self._player: mpv.MPV = self.__init_player()
        self.load_config()

    def _build_ui(self):
        self._src_file_le = QtWidgets.QLineEdit()
        self._src_file_le.setReadOnly(True)
        self._browse_src_pb = QtWidgets.QPushButton('Select File')
        self._threshold_sp = QtWidgets.QSpinBox()
        self._threshold_sp.wheelEvent = lambda event: None
        self._threshold_sp.setEnabled(False)
        self._threshold_sp.setRange(0, 100)
        self._threshold_sp.setValue(45)
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

        self._zoom_timeline_sl = QLabeledRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._zoom_timeline_sl.setEnabled(False)
        self._zoom_timeline_sl.setVisible(False)
        self._current_timecode_le = QtWidgets.QLineEdit('00:00:00:00')
        self._current_timecode_le.setMinimumWidth(100)
        self._current_timecode_le.setMaximumWidth(100)
        self._current_timecode_le.setEnabled(False)
        self._current_frame_sp = QtWidgets.QSpinBox()
        self._current_frame_sp.wheelEvent = lambda event: None
        self._current_frame_sp.setMinimumWidth(100)
        self._current_frame_sp.setMaximumWidth(100)
        self._current_frame_sp.setEnabled(False)
        self._add_marker_pb = QtWidgets.QPushButton('Add Marker')
        self._remove_marker_pb = QtWidgets.QPushButton('Remove Marker')

        self._otio_view = OTIOViewWidget(parent=self)
        self._export_dir_le = QtWidgets.QLineEdit()
        self._export_dir_le.setReadOnly(True)
        self._browse_dst_pb = QtWidgets.QPushButton('Browse Destination')
        self._import_pb = QtWidgets.QPushButton('Import')
        self._import_pb.setVisible(False)
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
        player_widget_lay.addStretch(3)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self._src_file_le, 0, 0, 1, 1)
        layout.addWidget(self._browse_src_pb, 0, 1, 1, 1)
        layout.addWidget(self._threshold_sp, 0, 2, 1, 1)
        layout.addWidget(self._process_pb, 0, 3, 1, 1)
        layout.addWidget(self._player_widget, 1, 0, 3, 4)
        layout.addWidget(self._shots_panel_lw, 1, 4, 6, 3)
        layout.addWidget(self._zoom_timeline_sl, 4, 0, 1, 2)
        marker_lay = QtWidgets.QHBoxLayout()
        marker_lay.addWidget(self._current_timecode_le)
        marker_lay.addWidget(self._current_frame_sp)
        marker_lay.addWidget(self._add_marker_pb)
        marker_lay.addWidget(self._remove_marker_pb)
        layout.addLayout(marker_lay, 4, 2, 1, 2)
        layout.addWidget(self._otio_view, 6, 0, 1, 4)
        layout.addWidget(self._export_dir_le, 7, 0, 1, 4)
        layout.addWidget(self._browse_dst_pb, 7, 4, 1, 1)
        layout.addWidget(self._export_pb, 7, 5, 1, 1)
        layout.addWidget(self._import_pb, 7, 6, 1, 1)
        self.setLayout(layout)

    def _connect_ui(self):
        self._browse_src_pb.clicked.connect(self._browse_input)
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

        self._zoom_timeline_sl.sliderReleased.connect(lambda: self._update_timeline_focus())
        self._current_frame_sp.valueChanged.connect(self._timeline_seek)

        self._add_marker_pb.clicked.connect(lambda: self._add_shot(self._current_frame_sp.value()))
        self._remove_marker_pb.clicked.connect(lambda: self._remove_shot(None, self._current_frame_sp.value()))

        self._browse_dst_pb.clicked.connect(self._browse_output)
        self._export_pb.clicked.connect(self._export_all)

        self._shots_panel_lw.sig_shot_range_changed.connect(self._update_shot_neighbors)
        self._shots_panel_lw.sig_shots_changed.connect(self.sort_shots)
        self._shots_panel_lw.sig_shot_deleted.connect(lambda x: self._remove_shot(None, shot_start=x))

        # OTIOview signals
        self._otio_view.timeline_widget.selection_changed.connect(self._timeline_selection_changed)
        self._otio_view.time_slider_clicked.connect(self._timeline_seek)
        self._otio_view.ruler_pressed.connect(lambda: self._pause_player(True))
        self._otio_view.ruler_moved.connect(self._timeline_seek)
        self._otio_view.ruler_released.connect(self._timeline_seek)
        self._otio_view.marker_added.connect(self._add_shot)
        self._otio_view.marker_moved.connect(self._update_shot_from_marker)
        self._otio_view.marker_removed.connect(self._remove_shot)

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

    def __init_player(self) -> mpv.MPV:
        # set mpv player and time observer callback
        player = mpv.MPV(wid=str(int(self._screen.winId())), keep_open='yes', framedrop='no')

        @player.property_observer('time-pos')
        def time_observer(_, value):
            self._time_observer(value)

        return player

    def _timeline_selection_changed(self, item):
        print('OTIO Selected Item : ', item)

    def _browse_input(self):
        last_source = Path(self._src_file_le.text())
        file_filter = f'Video files (*{" *".join(VALID_VIDEO_EXT)})'
        video_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Choose Source file', last_source.as_posix(),
                                                              file_filter)
        self._video_selected(video_path)

    def _video_selected(self, video_path: Path | str | None = None):
        video_path = Path(video_path or self._src_file_le.text())
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
        self.load_auto_save(video_path)

    def _browse_output(self):
        last_directory = Path(self._export_dir_le.text())
        output_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Output Directory',
                                                                 last_directory.as_posix(),
                                                                 QtWidgets.QFileDialog.ShowDirsOnly)
        self._export_dir_le.setText(output_path)
        self.wirte_auto_save()

    def load_auto_save(self, video_path: Path, save_path: Path = None):
        video_path = Path(video_path or self._src_file_le.text())
        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'auto_saves/{video_path.stem}.json'))
        if not temp_save_path.exists():
            return
        save_data = loads(temp_save_path.read_text())
        if not save_data.get('shots', []):
            return

        msg = 'A previous auto-save has been found, would you like to load it ?'
        msg_box = QtWidgets.QMessageBox.question(None, 'Load Auto-Save ?', msg)
        if msg_box == QtWidgets.QMessageBox.No:
            return
        self._threshold_sp.setValue(save_data.get('threshold', 45))
        self._export_dir_le.setText(save_data.get('export_directory', ''))
        self._shots_panel_lw.prefix = save_data.get('prefix', '')
        self._shots_panel_lw.start = save_data.get('shot_start', '')
        self._process_video(save_data=save_data['shots'])

    def wirte_auto_save(self, video_path: Path | str | None = None, save_path: Path | str | None = None):
        video_path = Path(video_path or self._src_file_le.text())
        export_dir = self._export_dir_le.text()
        wolverine_data = {
            'source': video_path.as_posix(),
            'threshold': self._threshold_sp.value(),
            'probe_data': self._probe_data.to_dict(),
            'prefix': self._shots_panel_lw.prefix,
            'shot_start': self._shots_panel_lw.start,
            'export_directory': Path(export_dir).as_posix() if export_dir else '',
            'shots': []
        }
        for shot in self.shots:
            wolverine_data['shots'].append(shot.to_dict())

        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'auto_saves/{video_path.stem}.json'))
        temp_save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_save_path.write_text(dumps(wolverine_data))

    def load_config(self, save_path: Path | str | None = None):
        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'config.json'))
        if not temp_save_path.exists():
            return

        last_open = loads(temp_save_path.read_text()).get('last_open', '')
        self._src_file_le.setText(Path(last_open).as_posix())

        if self._src_file_le.text():
            self.load_auto_save(self._src_file_le.text())
            enable_ui = bool(self._src_file_le.text())
            self._process_pb.setEnabled(enable_ui)
            self._threshold_sp.setEnabled(enable_ui)

    def save_config(self, video_path: Path | str | None = None, save_path: Path | str | None = None):
        video_path = Path(video_path or self._src_file_le.text())
        config_data = {'last_open': video_path.as_posix()}

        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'config.json'))
        temp_save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_save_path.write_text(dumps(config_data))

    def _process_video(self, save_data: Dict = None):
        video_path = Path(self._src_file_le.text())
        if not self._player or not video_path.exists():
            return

        self._probe_data = utils.probe_file(video_path)
        if not save_data:
            self.shots = utils.probe_file_shots(video_path, self._probe_data.fps, self._probe_data.frames,
                                                detection_threshold=self._threshold_sp.value())
        else:
            for shot_data in save_data:
                shot_data = shots.ShotData.from_dict(shot_data)
                shot_data.generate_thumbnail()
                self.shots.append(shot_data)

        if not self.shots:
            QtWidgets.QMessageBox.critical(self, 'Detection Error', 'Could not detect any shots in provided video !')
            return

        self.sort_shots()
        self._update_otio_timeline()
        self.wirte_auto_save(video_path)

        frame_range = (0, self._probe_data.frames)
        self._zoom_timeline_sl.blockSignals(True)
        self._zoom_timeline_sl.setTickInterval(1)
        self._zoom_timeline_sl.setRange(*frame_range)
        self._zoom_timeline_sl.setValue(frame_range)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setRange(*frame_range)
        self._shots_panel_lw.refresh_shots(self.shots)

        for slider in [self._current_frame_sp, self._zoom_timeline_sl]:
            slider.setEnabled(True)
            slider.blockSignals(False)
        self._player_controls_w.setEnabled(True)

        self._player.loadfile(video_path.as_posix())
        self._player.pause = True

    def _update_otio_timeline(self, video_path: Path | str | None = None):
        video_path = video_path or Path(self._src_file_le.text())
        # add shots to OTIO track
        track = schema.Track(
            name=video_path.stem,
            kind=schema.TrackKind.Video
        )
        for shot in self.shots:
            if shot.otio_clip.parent():
                shot.otio_clip.parent().remove(shot.otio_clip)
            track.append(shot.otio_clip)
        # add track to stack
        stack = schema.Stack(
            children=[track],
            name=video_path.stem,
        )
        # add stack to timeline
        self.timeline = schema.Timeline()
        self.timeline.tracks = stack
        self.timeline.metadata['source'] = video_path.as_posix()
        self._otio_view.load_timeline(self.timeline)
        self._otio_view.ruler.move_to_frame(self._current_frame_sp.value() or 0)

    def _find_closest_shots(self, frame: int) -> shots.ShotData:
        closest_shot = None
        for i, shot in enumerate(self.shots):
            if not (shot.start_frame <= frame <= shot.end_frame):
                continue
            closest_shot = shot
            break

        return closest_shot

    def sort_shots(self):
        if not self.shots:
            return

        self.shots = sorted(self.shots, key=lambda x: x.start_frame)
        # check if first shot starts at 0
        if self.shots[0].start_frame != 0:
            cur_first = self.shots[0]
            new_first = shots.ShotData(
                index=0,
                fps=cur_first.fps,
                source=cur_first.source,
                range=opentime.range_from_start_end_time_inclusive(
                    start_time=opentime.from_frames(0, cur_first.fps),
                    end_time_inclusive=opentime.from_frames((cur_first.start_frame - 1), cur_first.fps),
                ),
                ignored=True,
                enabled=False
            )
            new_first.generate_thumbnail()
            self.shots.insert(0, new_first)
        # reset shot indices
        index = 0
        for shot in self.shots:
            if shot.ignored:
                shot.index = (index * 10) + 5
                continue
            index += 1
            shot.index = index * 10
        # update UI and timeline and save in temp files
        self._update_otio_timeline()
        self._shots_panel_lw.refresh_shots(self.shots)
        self.wirte_auto_save(self._src_file_le.text())

    def _add_shot(self, start_frame: int, end_frame: int | None = None):
        closest_shot = self._find_closest_shots(start_frame)
        if not closest_shot:
            return False
        if end_frame is None:
            end_frame = closest_shot.end_frame
        if (start_frame, end_frame) == (closest_shot.start_frame, closest_shot.end_frame):
            return False

        new_shot = shots.ShotData(
            index=0,
            source=Path(self._src_file_le.text()),
            fps=self._probe_data.fps,
            range=opentime.range_from_start_end_time_inclusive(
                start_time=opentime.from_frames(start_frame, self._probe_data.fps),
                end_time_inclusive=opentime.from_frames(end_frame, self._probe_data.fps)
            )
        )
        closest_shot.end_frame = (start_frame - 1)

        self.shots.append(new_shot)
        self.sort_shots()

    def _update_shot_from_marker(self, marker: schema.Marker, new_start: int):
        old_start = marker.marked_range.start_time.to_frames()
        if old_start == new_start:
            return False
        closest_shot = self._find_closest_shots(old_start)
        if not closest_shot:
            return False
        prev_range = (closest_shot.start_frame, closest_shot.end_frame)
        closest_shot.start_frame = new_start
        closest_shot.generate_thumbnail()
        self._update_shot_neighbors(closest_shot, prev_range)

    def _remove_shot(self, marker: schema.Marker | None, shot_start: int):
        if marker:
            shot_start = marker.marked_range.start_time.to_frames()
        closest_shot = self._find_closest_shots(shot_start)
        prev_shot = [s for s in self.shots if s.end_frame == (closest_shot.start_frame - 1)]
        if prev_shot:
            prev_shot[0].end_frame = closest_shot.end_frame
        self.shots.remove(closest_shot)

        self.sort_shots()

    def _update_shot_neighbors(self, shot_data: shots.ShotData, prev_range: tuple[int, int]):
        prev_start, prev_end = prev_range
        prev_shot = [s for s in self.shots if s != shot_data and s.end_frame == (prev_start - 1)]
        next_shot = [s for s in self.shots if s != shot_data and s.start_frame == (prev_end + 1)]
        if prev_shot:
            prev_shot[0].end_frame = shot_data.start_frame - 1
        if next_shot:
            next_shot[0].start_frame = shot_data.end_frame + 1
            next_shot[0].generate_thumbnail()

        self.sort_shots()

    def _update_timeline_focus(self, new_range: Tuple[int, int] = None):
        start, end = new_range or self._zoom_timeline_sl.value()
        current_frame = self._current_frame_sp.value()
        if not (start <= current_frame <= end):
            self._current_frame_sp.setValue(start if current_frame < start else end)
            current_time = opentime.to_timecode(opentime.from_frames(current_frame, self._probe_data.fps))
            self._current_timecode_le.setText(current_time)

    def _time_observer(self, value: float):
        if not self._probe_data or not value:
            return
        current_frame = opentime.to_frames(opentime.from_seconds(value, self._probe_data.fps))
        current_time = opentime.to_timecode(opentime.from_seconds(value, self._probe_data.fps))
        self._otio_view.ruler.move_to_frame(current_frame)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setValue(int(current_frame))
        self._current_frame_sp.blockSignals(False)
        self._current_timecode_le.setText(current_time)
        QtWidgets.QApplication.processEvents()

    def _timeline_seek(self, value: Union[int, float] = None):
        if not self._probe_data:
            return
        value = value if isinstance(value, (int, float)) else self._current_frame_sp.value()
        value_seconds = opentime.to_seconds(opentime.from_frames(value, self._probe_data.fps))
        self._otio_view.ruler.move_to_frame(value)
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
            self._timeline_seek(0.0)
        elif key == QtCore.Qt.Key_Left:
            self._player.frame_back_step()
        elif key == QtCore.Qt.Key_Right:
            self._player.frame_step()
        elif key == QtCore.Qt.Key_P:
            self._pause_player(True)
            current_frame = self._current_frame_sp.value()
            prev_start = max([s.start_frame for s in self.shots if s.start_frame < current_frame] or [0])
            self._timeline_seek(prev_start)
        elif key == QtCore.Qt.Key_N:
            self._pause_player(True)
            current_frame = self._current_frame_sp.value()
            next_start = max([s.start_frame for s in self.shots if s.start_frame > current_frame] or [0])
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

    def _export_all(self):
        if not self._export_dir_le.text():
            QtWidgets.QMessageBox.critical(self, 'Output Error', 'No Output Directory Selected !')
            return

        export_path = Path(self._export_dir_le.text())
        export_path.mkdir(parents=True, exist_ok=True)

        for shot in self.shots:
            shot.save_directory = export_path
            shot.generate_thumbnail()
            shot.generate_movie()
            shot.generate_audio()

        self._update_otio_timeline()
        timeline_outputs = [
            ('otio_json', '.otio'),
            ('cmx_3600', '.edl'),
            ('fcp_xml', '.xml'),
        ]
        input_name = Path(self._src_file_le.text()).stem
        for adapter, extension in timeline_outputs:
            output_path = export_path.joinpath(f'{input_name}{extension}')
            adapters.write_to_file(self.timeline, output_path.as_posix(), adapter_name=adapter)

        export_errors = 0
        for export_action in self._export_actions:
            try:
                export_action.func(self._export_dir_le.text(), self.shots)
            except Exception as e:
                log.critical(f'Export Failed: \nError: {e}\nExport Action :{export_action}')
                export_errors += 1

        err_msg = f'\n {export_errors} errors were encountered, check logs for more details' if export_errors else ''
        QtWidgets.QMessageBox.information(self, 'Wolverine Export', f'Export done !{err_msg}')

    def add_export_action(self, export_action: ExportAction):
        self._export_actions.append(export_action)


def export_seer(dest_path: Path, shot_list: list[shots.ShotData]):
    import seer
    from overseer.utils import seer_tools
    from brio import media
    from seer_ui.dialogs.project_picker import ProjectDialog

    proj_diag = ProjectDialog()
    proj_diag.move(QtGui.QCursor.pos())
    if not proj_diag.exec_():
        return

    project = proj_diag.chosen_project()
    project = seer.get_project(project.lower())
    shots_grp = project.group('shots')

    output_path = Path(dest_path)
    output_path.mkdir(parents=True, exist_ok=True)

    for shot_data in shot_list:
        if not shot_data.enabled or shot_data.ignored:
            continue
        try:
            wu = project.workunit(shot_data.name)
        except Exception:
            wu = seer_tools.create_workunit(project, shot_data.name, 'shot', shots_grp)
            seer_tools.create_entity_dirs_on_disk(wu)
        wu.set_setting('frame_range', (shot_data.new_start, shot_data.new_end), overwrite=True)

        media.set_thumbnail(shot_data.thumbnail.as_posix(), wu)
        media.set_preview(shot_data.movie.as_posix(), wu)


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ui = WolverineUI()
    ui.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
    ui.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
    ui.show()
    ui.raise_()

    seer_export_action = ExportAction(description='Seer Export', func=export_seer)
    ui.add_export_action(seer_export_action)

    sys.exit(app.exec_())


