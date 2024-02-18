from __future__ import annotations

import os
import sys
from pathlib import Path
from json import loads, dumps
from dataclasses import dataclass
from typing import Callable, Any

import mpv
from superqt import QLabeledRangeSlider, QLabeledSlider, QCollapsible
from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from opentimelineio import opentime, schema, adapters

from wolverine import log
from wolverine import shots
from wolverine import utils
from wolverine.ui_utils import ONE_BILLION, get_icon, OTIOViewWidget

VALID_VIDEO_EXT = ['.mov', '.mp4', '.mkv', '.avi']
TEMP_SAVE_DIR = Path(os.getenv('WOLVERINE_PREFS_PATH', Path.home())).joinpath('wolverine')


# TODO split player and player controlls into their own widget with an event filter
# TODO set volume value to 0 when mute and to previous value when not
# TODO split ui into different modules
# TODO when playing select current shot in shots list, when clicking shot junp to shot start in timeline, when double clicking shot ab-loop over it
# TODO change shots layout to resizable grid
# TODO run shot detection in background and update shots thumbnail/video in background
# TODO add parent sequence selection and add clips representing sequences with different colors (add toggle sequences in timeline button too)
# TODO add ab-loop over range in player
#    use mpv command : self._player.command('ab-loop-a', shot_start_time); self._player.command('ab-loop-b', shot_end_time)
#    or set : self._player.ab_loop_a = shot_start_time; self._player.ab_loop_b = shot_end_time
#    or set : start/end and loop in mpv : self._player.start = shot_start_time; self._player.end = shot_end_time; self._player.loop = True
# TODO show video info in a widget (fps, frames, duration, resolution)

# TODO test with an actual edit file and check if metadata is still present when re-exported from premiere/afterfx
# FIXME current frame spinbox and otio ruler sometimes don't have same value
# TODO make sur shots aren't duplicated
# TODO add log file
# TODO add unit tests

# TODO override opentimelineview's UI
#  - find a way to zoom in on specific parts of the timeline
#  - prevent timeline from resetting zoom everytime it is updated
#  - maybe split all external timeline files (otio, edl, etc...) into two timeline, one that corresponds to the
#     actual file, the other which is flattened by wolverine using (use otiotool.flatten_timeline) ?

# TODO enable add marker button only if current frame doesn't already have a marker
# TODO enable remove marker button only if current frame has a marker
# TODO add framerate selection and use (is_valid_timecode_rate and nearest_valid_timecode_rate) to check/get correct fps
# TODO use opentime.rescaled_to to get correct ranges when fps from movie != fps in UI
# FIXME keyboard shortcuts get overriden by dialog (make don't use QDialog)

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
    widget: QtWidgets.QWidget | None = None
    widget_func: str = ''


class ExportActionsUi(QtWidgets.QDialog):

    def __init__(self, export_actions: list[ExportAction], parent: QtWidgets.QWidget = None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle('Wolverine - Export Actions')

        self._export_actions = export_actions
        self._action_widgets = []
        self._build_ui()

    def _build_ui(self):
        self._shot_thumbs_cb = QtWidgets.QCheckBox()
        self._shot_movies_cb = QtWidgets.QCheckBox()
        self._shot_audio_cb = QtWidgets.QCheckBox()

        shot_fl = QtWidgets.QFormLayout()
        shots_gb = QtWidgets.QGroupBox('Shots :')
        shots_gb.setLayout(shot_fl)
        shot_fl.addRow('Export Thumbnails :', self._shot_thumbs_cb)
        shot_fl.addRow('Export Movie Clips :', self._shot_movies_cb)
        shot_fl.addRow('Export Audio Clips :', self._shot_audio_cb)

        self._tl_edl_cb = QtWidgets.QCheckBox()
        self._tl_xml_cb = QtWidgets.QCheckBox()
        self._tl_otio_cb = QtWidgets.QCheckBox()

        timelines_fl = QtWidgets.QFormLayout()
        timelines_gb = QtWidgets.QGroupBox('Timeline :')
        timelines_gb.setLayout(timelines_fl)
        timelines_fl.addRow('Export CMX 3600 (.edl) :', self._tl_edl_cb)
        timelines_fl.addRow('Export Final Pro (.xml) :', self._tl_xml_cb)
        timelines_fl.addRow('Export OpenTimelineIO (.otio) :', self._tl_otio_cb)

        for widget in [self._shot_thumbs_cb, self._shot_movies_cb, self._shot_audio_cb,
                       self._tl_edl_cb, self._tl_xml_cb, self._tl_otio_cb]:
            widget.setChecked(True)

        actions_lay = QtWidgets.QVBoxLayout()
        actions_gb = QtWidgets.QGroupBox('Custom Actions :')
        actions_gb.setLayout(actions_lay)
        for export_action in self._export_actions:
            action_parent = QCollapsible(export_action.description)
            action_parent.expand(animate=False)
            actions_lay.addWidget(action_parent)
            enable_action_cb = QtWidgets.QCheckBox(export_action.description)
            action_parent.addWidget(enable_action_cb)
            if not export_action.widget and export_action.widget_func:
                self._action_widgets.append((enable_action_cb, None, None))
                continue
            action_widget = export_action.widget()
            action_widget.setEnabled(False)
            action_parent.addWidget(action_widget)
            enable_action_cb.stateChanged.connect(lambda x: action_widget.setEnabled(enable_action_cb.isChecked()))
            self._action_widgets.append((enable_action_cb, export_action, action_widget))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(actions_gb)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(300)

        export_btn = QtWidgets.QPushButton('Export')
        export_btn.clicked.connect(self.accept)
        cancel_btn = QtWidgets.QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btns_lay = QtWidgets.QHBoxLayout()
        btns_lay.addWidget(export_btn)
        btns_lay.addWidget(cancel_btn)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(shots_gb)
        layout.addWidget(timelines_gb)
        if self._export_actions:
            layout.addWidget(scroll)
        layout.addLayout(btns_lay)
        self.setLayout(layout)

    @property
    def export_actions(self) -> dict[str, Any]:
        shots = [
            ('thumbnails', self._shot_thumbs_cb.isChecked()),
            ('movies', self._shot_movies_cb.isChecked()),
            ('audio', self._shot_audio_cb.isChecked()),
        ]
        timelines = [
            ('.edl', self._tl_edl_cb.isChecked()),
            ('.xml', self._tl_xml_cb.isChecked()),
            ('.otio', self._tl_otio_cb.isChecked()),
        ]

        actions = {
            'shots': [label for label, enabled in shots if enabled],
            'timeline': [label for label, enabled in timelines if enabled],
            'custom': []
        }
        for (enabled_cb, export_action, action_widget) in self._action_widgets:
            if not enabled_cb.isChecked():
                continue
            if not action_widget:
                actions['custom'].append((export_action, None))
                continue
            widget_value = getattr(action_widget, export_action.widget_func)()
            actions['custom'].append((export_action, widget_value))
        return actions

    @classmethod
    def get_export_actions(cls, export_actions):
        dialog = cls(export_actions=export_actions)
        result = dialog.exec_()
        export_actions = dialog.export_actions
        return bool(result), export_actions


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

    @property
    def name(self):
        return self._shot_name_lb.text()

    # @property
    # def active(self):
    #     return self._active
    #
    # @active.setter
    # def active(self, value: bool):
    #     self.setStyleSheet('#ShotWidget {border: 1px solid black;}')

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

        opts_lay = QtWidgets.QHBoxLayout()
        opts_lay.addWidget(QtWidgets.QLabel('Shots Prefix :'))
        opts_lay.addWidget(self._shots_prefix_le)
        opts_lay.addWidget(QtWidgets.QLabel('Shots Start :'))
        opts_lay.addWidget(self._shots_start_sp)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(opts_lay)
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

    def refresh_shots(self, shot_list: list[shots.ShotData]):
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
        self._shot_list_lw.layout().addStretch(3)
        return self.shot_widgets


class Player(QtWidgets.QDialog):

    sig_player_shortcut = QtCore.Signal(int)
    sig_player_volume = QtCore.Signal(int)
    sig_player_speed = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget = None) -> None:
        super().__init__(parent=parent)

        self._build_ui()
        self._connect_ui()

    def _build_ui(self):
        self._screen = QtWidgets.QFrame()
        self._screen.setMinimumSize(675, 675)

        self._loop_pb = QtWidgets.QPushButton()
        self._loop_pb.setToolTip('Loop')
        self._loop_pb.setIcon(get_icon('loop.png'))
        # self._loop_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._speed_sl = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
        self._speed_sl.setRange(1, 100)
        self._speed_sl.setValue(100)
        # self._speed_sl.setFocusPolicy(QtCore.Qt.NoFocus)
        self._prev_shot_pb = QtWidgets.QPushButton()
        self._prev_shot_pb.setToolTip('Previous Shot')
        self._prev_shot_pb.setIcon(get_icon('previous_shot.png'))
        # self._prev_shot_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._prev_frame_pb = QtWidgets.QPushButton()
        self._prev_frame_pb.setToolTip('Previous Frame')
        self._prev_frame_pb.setIcon(get_icon('previous_frame.png'))
        # self._prev_frame_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._stop_pb = QtWidgets.QPushButton()
        self._stop_pb.setToolTip('Stop')
        self._stop_pb.setIcon(get_icon('stop.png'))
        # self._stop_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._pause_pb = QtWidgets.QPushButton()
        self._pause_pb.setToolTip('Pause')
        self._pause_pb.setIcon(get_icon('pause.png'))
        # self._pause_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._next_frame_pb = QtWidgets.QPushButton()
        self._next_frame_pb.setToolTip('Next Frame')
        self._next_frame_pb.setIcon(get_icon('next_frame.png'))
        # self._next_frame_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._next_shot_pb = QtWidgets.QPushButton()
        self._next_shot_pb.setToolTip('Next Shot')
        self._next_shot_pb.setIcon(get_icon('next_shot.png'))
        # self._next_shot_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._mute_pb = QtWidgets.QPushButton()
        self._mute_pb.setToolTip('Mute')
        self._mute_pb.setIcon(get_icon('mute.png'))
        # self._mute_pb.setFocusPolicy(QtCore.Qt.NoFocus)
        self._volume_sl = QLabeledSlider(QtCore.Qt.Orientation.Horizontal)
        self._volume_sl.setRange(0, 100)
        self._volume_sl.setValue(100)
        # self._volume_sl.setFocusPolicy(QtCore.Qt.NoFocus)
        self._fullscreen_pb = QtWidgets.QPushButton()
        self._fullscreen_pb.setToolTip('Fullscreen')
        self._fullscreen_pb.setIcon(get_icon('fullscreen.png'))
        # self._fullscreen_pb.setFocusPolicy(QtCore.Qt.NoFocus)

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
        controls_lay.addStretch(3)
        self._player_controls_w.setLayout(controls_lay)
        self._player_controls_w.setEnabled(False)
        # self._player_controls_w.keyPressEvent = self.keyPressEvent
        # self._player_controls_w.installEventFilter(self)
        # self.installEventFilter(self)

        screen_ctrl_lay = QtWidgets.QVBoxLayout()
        screen_ctrl_lay.addWidget(self._screen, stretch=10)
        screen_ctrl_lay.addWidget(self._player_controls_w, stretch=10)

        self.setLayout(screen_ctrl_lay)

    # def eventFilter(self, source, event):
    #     # if event.type() not in [QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease]:
    #     if event.type() not in [QtCore.QEvent.KeyRelease]:
    #         # event.ignore()
    #         # return True
    #         return super().eventFilter(source, event)
    #     print('*'*50)
    #     print('event.key ===> ', event.key())
    #     print('source ===> ', source)
    #     self.sig_player_shortcut.emit(event.key())
    #     event.ignore()
    #     return True
    #     # return super().eventFilter(source, event)

    # def keyPressEvent(self, event):
    #     print('*'*50)
    #     print('keyPressEvent.key ===> ', event.key())

    def _connect_ui(self):
        self._speed_sl.valueChanged.connect(self.sig_player_volume.emit)
        self._volume_sl.valueChanged.connect(self.sig_player_speed.emit)
        self._loop_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_L))
        self._prev_shot_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_P))
        self._prev_frame_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_Left))
        self._stop_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_S))
        self._pause_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_Space))
        self._next_frame_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_Right))
        self._next_shot_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_N))
        self._mute_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_M))
        self._fullscreen_pb.clicked.connect(lambda: self.sig_player_shortcut.emit(QtCore.Qt.Key_F))

    @property
    def screen(self):
        return self._screen

    @property
    def controls(self):
        return self._player_controls_w


class WolverineUI(QtWidgets.QDialog):

    def __init__(self, parent: QtWidgets.QWidget = None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle('Wolverine - Sequence Splitter')

        self._full_screen: bool = False
        self._last_pause_state: bool = True
        self._probe_data: utils.FFProbe | None = None
        self.shots: list[shots.ShotData] = []
        self.timeline = None
        self._export_actions: list[ExportAction] = []

        self._build_ui()
        self._connect_ui()
        # self.installEventFilter(self)

        self._player: mpv.MPV = self.__init_player()

    def _build_ui(self):
        self._src_file_le = QtWidgets.QLineEdit()
        self._src_file_le.setReadOnly(True)
        self._browse_src_pb = QtWidgets.QPushButton('Select File')
        self._threshold_sp = QtWidgets.QSpinBox()
        self._threshold_sp.setToolTip('Shot Detection Threshold (1-100)')
        self._threshold_sp.wheelEvent = lambda event: None
        self._threshold_sp.setEnabled(False)
        self._threshold_sp.setRange(1, 100)
        self._threshold_sp.setValue(45)
        self._process_pb = QtWidgets.QPushButton('Process')
        self._process_pb.setEnabled(False)

        self._zoom_timeline_sl = QLabeledRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._zoom_timeline_sl.setValue((0, 100))
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
        self._add_marker_pb.setEnabled(False)
        self._remove_marker_pb = QtWidgets.QPushButton('Remove Marker')
        self._remove_marker_pb.setEnabled(False)

        self._otio_view = OTIOViewWidget(parent=self)
        self._export_dir_le = QtWidgets.QLineEdit()
        self._export_dir_le.setReadOnly(True)
        self._browse_dst_pb = QtWidgets.QPushButton('Browse Destination')
        self._import_pb = QtWidgets.QPushButton('Import')
        self._import_pb.setVisible(False)
        self._export_pb = QtWidgets.QPushButton('Export')
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setVisible(False)
        self._progress_bar_msg = QtWidgets.QLabel()
        self._progress_bar_msg.setVisible(False)
        self._shots_panel_lw = ShotListWidget()

        self._player_widget = Player()

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        splitter.addWidget(self._player_widget)
        splitter.addWidget(self._shots_panel_lw)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self._src_file_le, 0, 0, 1, 3)
        layout.addWidget(self._browse_src_pb, 0, 3, 1, 1)
        layout.addWidget(self._import_pb, 0, 4, 1, 1)
        layout.addWidget(self._threshold_sp, 0, 5, 1, 1)
        layout.addWidget(self._process_pb, 0, 6, 1, 1)
        layout.addWidget(splitter, 1, 0, 3, 7)
        layout.addWidget(self._zoom_timeline_sl, 5, 0, 1, 5)
        marker_lay = QtWidgets.QHBoxLayout()
        marker_lay.addWidget(self._current_timecode_le)
        marker_lay.addWidget(self._current_frame_sp)
        marker_lay.addWidget(self._add_marker_pb)
        marker_lay.addWidget(self._remove_marker_pb)
        layout.addLayout(marker_lay, 5, 5, 1, 2)
        layout.addWidget(self._otio_view, 6, 0, 1, 7)
        layout.addWidget(self._export_dir_le, 7, 0, 1, 5)
        layout.addWidget(self._browse_dst_pb, 7, 5, 1, 1)
        layout.addWidget(self._export_pb, 7, 6, 1, 1)
        layout.addWidget(self._progress_bar, 8, 0, 1, 5)
        layout.addWidget(self._progress_bar_msg, 8, 5, 1, 2)
        self.setLayout(layout)

    def _connect_ui(self):
        self._browse_src_pb.clicked.connect(self._browse_input)
        self._src_file_le.editingFinished.connect(self._video_selected)
        self._process_pb.clicked.connect(self._process_video)

        self._player_widget.sig_player_shortcut.connect(self._player_controls)
        self._player_widget.sig_player_volume.connect(self._set_player_volume)
        self._player_widget.sig_player_speed.connect(self._set_player_speed)

        self._zoom_timeline_sl.sliderReleased.connect(lambda: self._update_timeline_focus())
        self._current_frame_sp.valueChanged.connect(self._timeline_seek)

        self._add_marker_pb.clicked.connect(lambda: self._add_shot(self._current_frame_sp.value()))
        self._remove_marker_pb.clicked.connect(lambda: self._remove_shot(None, self._current_frame_sp.value()))

        self._browse_dst_pb.clicked.connect(self._browse_output)
        self._export_pb.clicked.connect(self._open_export_dialog)

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

    # def eventFilter(self, source, event):
    #     # if event.type() not in [QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease]:
    #     if event.type() not in [QtCore.QEvent.KeyRelease]:
    #         return super().eventFilter(source, event)
    #     print('*'*50)
    #     print('event.key ===> ', event.key())
    #     print('source ===> ', source)
    #     shortcut_found = self._player_controls(event.key())
    #     if shortcut_found:
    #         return True
    #     return super().eventFilter(source, event)

    # def keyPressEvent(self, event):
    #     print('wolverine keyPressEvent ==> ', event)

    def __init_player(self) -> mpv.MPV:
        # set mpv player and time observer callback
        player = mpv.MPV(wid=str(int(self._player_widget.screen.winId())), keep_open='yes', framedrop='no')

        @player.property_observer('time-pos')
        def time_observer(_, value):
            self._time_observer(value)

        return player

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
        # save last open
        self.save_config(video_path)
        # check if an auto-save exists for file, if so load it
        save_loaded = self.load_auto_save(video_path)
        # if no auto save loaded, just load the video in the payer
        if not save_loaded:
            self._load_video(video_path)

    def _load_video(self, video_path: Path):
        self._process_pb.setEnabled(True)
        self._threshold_sp.setEnabled(True)

        self._probe_data = utils.probe_file(video_path)
        if not self._probe_data:
            err_msg = 'The file you have selected cannot be probed'
            QtWidgets.QMessageBox.critical(self, 'File Selection Error', err_msg)
            raise ValueError(err_msg)

        frame_range = (0, self._probe_data.frames)
        self._zoom_timeline_sl.blockSignals(True)
        self._zoom_timeline_sl.setTickInterval(1)
        self._zoom_timeline_sl.setRange(*frame_range)
        self._zoom_timeline_sl.setValue(frame_range)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setRange(*frame_range)

        for slider in [self._current_frame_sp, self._zoom_timeline_sl]:
            slider.setEnabled(True)
            slider.blockSignals(False)
        # self._player_controls_w.setEnabled(True)
        self._player_widget.controls.setEnabled(True)
        self._current_timecode_le.setEnabled(True)
        self._add_marker_pb.setEnabled(True)
        self._remove_marker_pb.setEnabled(True)

        self._player.loadfile(video_path.as_posix())
        self._player.pause = True

    def _browse_output(self):
        last_directory = Path(self._export_dir_le.text())
        output_path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Output Directory',
                                                                 last_directory.as_posix(),
                                                                 QtWidgets.QFileDialog.ShowDirsOnly)
        self._export_dir_le.setText(output_path)
        self.write_auto_save()

    def load_auto_save(self, video_path: Path, save_path: Path = None) -> bool:
        video_path = Path(video_path or self._src_file_le.text())
        if not video_path.exists():
            return False
        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'auto_saves/{video_path.stem}.json'))
        if not temp_save_path.exists():
            return False
        save_data = loads(temp_save_path.read_text())
        if not save_data.get('shots', []):
            return False

        msg = 'A previous auto-save has been found, would you like to load it ?'
        msg_box = QtWidgets.QMessageBox.question(None, 'Load Auto-Save ?', msg)
        if msg_box == QtWidgets.QMessageBox.No:
            return False
        self._threshold_sp.setValue(save_data.get('threshold', 45))
        self._export_dir_le.setText(save_data.get('export_directory', ''))
        self._shots_panel_lw.prefix = save_data.get('prefix', '')
        self._shots_panel_lw.start = save_data.get('shot_start', '')
        self._process_video(save_data=save_data['shots'])
        return True

    def write_auto_save(self, video_path: Path | str | None = None, save_path: Path | str | None = None):
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

        last_open = Path(loads(temp_save_path.read_text()).get('last_open', ''))
        if not last_open.exists():
            return

        self._src_file_le.setText(last_open.as_posix())
        save_loaded = self.load_auto_save(last_open)
        if not save_loaded:
            self._load_video(last_open)

    def save_config(self, video_path: Path | str | None = None, save_path: Path | str | None = None):
        video_path = Path(video_path or self._src_file_le.text())
        config_data = {'last_open': video_path.as_posix()}

        temp_save_path = Path(save_path or TEMP_SAVE_DIR.joinpath(f'config.json'))
        temp_save_path.parent.mkdir(parents=True, exist_ok=True)
        temp_save_path.write_text(dumps(config_data))

    def _process_video(self, save_data = None):
        video_path = Path(self._src_file_le.text())
        if not self._player or not video_path.exists():
            return

        self._load_video(video_path)

        new_data = True
        if not save_data:
            shots_data = utils.probe_file_shots(video_path, self._probe_data.fps, self._probe_data.frames,
                                                detection_threshold=self._threshold_sp.value())
            nb_shots = next(save_data)
            save_data = shots_data if nb_shots else []
        else:
            nb_shots = len(save_data)
            new_data = False

        self.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar_msg.setVisible(True)
        self._progress_bar.setRange(0, nb_shots)
        for nb_shot, shot_data in enumerate(save_data):
            if not new_data:
                shot_data = shots.ShotData.from_dict(shot_data)
                shot_data.generate_thumbnail()
            self.shots.append(shot_data)
            self._progress_bar.setValue(nb_shot + 1)
            self._progress_bar_msg.setText('Probing' if new_data else 'Loading' + f' Shots ({(nb_shot+1)}/{nb_shots})')
            QtWidgets.QApplication.processEvents()
        self._progress_bar.setVisible(False)
        self._progress_bar_msg.setText('')
        self._progress_bar_msg.setVisible(False)
        self.setEnabled(True)

        if not self.shots:
            QtWidgets.QMessageBox.critical(self, 'Detection Error', 'Could not detect any shots in provided video !')
            return

        self.sort_shots()
        self._update_otio_timeline()
        self.write_auto_save(video_path)
        self._shots_panel_lw.refresh_shots(self.shots)

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

    def _timeline_selection_changed(self, item):
        print('OTIO Selected Item : ', item)
        # shot_name = item.name
        # for shot_widget in self._shots_panel_lw.shot_widgets:
        #     if shot_widget.name.lower() != shot_name:
        #         shot_widget.active = False
        #         continue
        #     shot_widget.active = True

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
        self.write_auto_save(self._src_file_le.text())

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

    def _remove_shot(self, marker: schema.Marker | None, shot_start: int) -> None:
        if not self.shots:
            return
        if marker:
            shot_start = marker.marked_range.start_time.to_frames()
        closest_shot = self._find_closest_shots(shot_start)
        prev_shot = [s for s in self.shots if s.end_frame == (closest_shot.start_frame - 1)]
        if prev_shot:
            prev_shot[0].end_frame = closest_shot.end_frame
        self.shots.remove(closest_shot)

        self.sort_shots()

    def _update_shot_neighbors(self, shot_data: shots.ShotData, prev_range: tuple[int, int]) -> None:
        prev_start, prev_end = prev_range
        prev_shot = [s for s in self.shots if s != shot_data and s.end_frame == (prev_start - 1)]
        next_shot = [s for s in self.shots if s != shot_data and s.start_frame == (prev_end + 1)]
        if prev_shot:
            prev_shot[0].end_frame = shot_data.start_frame - 1
        if next_shot:
            next_shot[0].start_frame = shot_data.end_frame + 1
            next_shot[0].generate_thumbnail()

        self.sort_shots()

    def _update_timeline_focus(self, new_range: tuple[int, int] = None):
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
        if self.shots:
            self._otio_view.ruler.move_to_frame(current_frame)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setValue(int(current_frame))
        self._current_frame_sp.blockSignals(False)
        self._current_timecode_le.setText(current_time)
        QtWidgets.QApplication.processEvents()

    def _timeline_seek(self, value: int | float = None):
        if not self._probe_data:
            return
        value = value if isinstance(value, (int, float)) else self._current_frame_sp.value()
        value_seconds = opentime.to_seconds(opentime.from_frames(value, self._probe_data.fps))
        if self.shots:
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
            return False
        if key == QtCore.Qt.Key_Space:
            self._player.pause = not self._player.pause
        elif key == QtCore.Qt.Key_S:
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
            # self._volume_sl.setValue(0 if not self._player.mute else 100)
            self._player.mute = not self._player.mute
        elif key == QtCore.Qt.Key_L:
            self._player.loop = not self._player.loop
        elif key == QtCore.Qt.Key_F:
            if self._full_screen:
                self._player_widget.screen.showNormal()
                # self.showNormal()
            else:
                self._player_widget.screen.showFullScreen()
                # self.showFullScreen()
            self._full_screen = not self._full_screen
            # self._player.fullscreen = not self._player.fullscreen  # not working
        else:
            return False
        return True

    def add_export_action(self, export_action: ExportAction):
        self._export_actions.append(export_action)

    def _open_export_dialog(self):
        if not self.shots:
            QtWidgets.QMessageBox.critical(self, 'Shot list Error', 'No Shots ot export !')
            return
        if not self._export_dir_le.text():
            QtWidgets.QMessageBox.critical(self, 'Output Error', 'No Output Directory Selected !')
            return

        user_accepted, export_actions = ExportActionsUi.get_export_actions(export_actions=self._export_actions)
        if not user_accepted:
            return

        self.setEnabled(False)
        export_path = Path(self._export_dir_le.text())
        export_path.mkdir(parents=True, exist_ok=True)

        # export shots
        self._progress_bar.setVisible(True)
        self._progress_bar_msg.setVisible(True)
        self._progress_bar.setRange(0, len(self.shots))
        for i, shot in enumerate(self.shots):
            self._progress_bar.setValue(i + 1)
            self._progress_bar_msg.setText(f'Exporting Shots ({(i+1)}/{len(self.shots)})')
            shot.save_directory = export_path
            if 'thumbnails' in export_actions['shots']:
                shot.generate_thumbnail()
            if 'movies' in export_actions['shots']:
                shot.generate_movie()
            if 'audio' in export_actions['shots']:
                shot.generate_audio()
            QtWidgets.QApplication.processEvents()

        # export timelines
        self._update_otio_timeline()
        timeline_outputs = [
            ('otio_json', '.otio'),
            ('cmx_3600', '.edl'),
            ('fcp_xml', '.xml'),
        ]
        # filter timeline outputs
        timeline_outputs = [(a, e) for a, e in timeline_outputs if e in export_actions['timeline']]
        # do export
        input_name = Path(self._src_file_le.text()).stem
        self._progress_bar.setRange(0, len(timeline_outputs))
        for i, (adapter, extension) in enumerate(timeline_outputs):
            self._progress_bar.setValue(i + 1)
            self._progress_bar_msg.setText(f'Exporting Timelines [{extension}] ({(i+1)}/{len(timeline_outputs)})')
            output_path = export_path.joinpath(f'{input_name}{extension}')
            adapters.write_to_file(self.timeline, output_path.as_posix(), adapter_name=adapter)

        # run custom export actions
        export_errors = 0
        custom_actions = export_actions.get('custom')
        self._progress_bar.setRange(0, len(custom_actions))
        for i, (export_action, widget_value) in enumerate(custom_actions):
            self._progress_bar.setValue(i + 1)
            self._progress_bar_msg.setText(f'Running Export Actions ({(i+1)}/{len(self._export_actions)})')

            widget_value = widget_value or []
            widget_value = widget_value if isinstance(widget_value, list) else [widget_value]
            try:
                export_action.func(self._export_dir_le.text(), self.shots, *widget_value)
            except Exception as e:
                log.critical(f'Export Failed: \nError: {e}\nExport Action :{export_action}')
                export_errors += 1

        self._progress_bar.setVisible(False)
        self._progress_bar_msg.setText('')
        self._progress_bar_msg.setVisible(False)
        self.setEnabled(True)

        err_msg = f'\n {export_errors} errors were encountered, check logs for more details' if export_errors else ''
        QtWidgets.QMessageBox.information(self, 'Wolverine Export', f'Export done !{err_msg}')


def open_ui():
    import qdarktheme
    _app = QtWidgets.QApplication(sys.argv)
    # Apply the complete dark theme to your Qt App.
    qdarktheme.setup_theme()

    _window = WolverineUI()
    _window.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
    _window.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
    _window.show()
    _window.raise_()

    # load auto-save
    _window.load_config()

    return _app, _window


if __name__ == '__main__':
    app, window = open_ui()
    sys.exit(app.exec_())



