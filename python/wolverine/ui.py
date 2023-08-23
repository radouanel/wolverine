
import sys
from pathlib import Path
from math import ceil, floor
from typing import Union, List

import mpv
from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from superqt import QRangeSlider, QLabeledSlider

from wolverine import utils


VALID_VIDEO_EXT = ['.mov', '.mp4', '.mkv', '.avi']
ONE_BILLION = 10**9  # type: int

# TODO use timecode module !
# TODO get split data from ffmpeg
# TODO split shots
# TODO show video info in a widget (fps, frames, duration, resolution)
# FIXME prev/next frame sometimes stuck between frames
# FIXME keyboard shortcuts get overriden by dialog
# TODO add marker timeline zoom slider (use QRangeSlider with two handles)


def pixel_pos_to_range_val(widget: QtWidgets.QWidget, pos: int):
    # more accurate than superqts same function
    opt = QtWidgets.QStyleOptionSlider()
    widget.initStyleOption(opt)
    gr = widget.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderGroove, widget)
    sr = widget.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderHandle, widget)

    if widget.orientation() == QtCore.Qt.Horizontal:
        slider_length = sr.width()
        slider_min = gr.x()
        slider_max = gr.right() - slider_length + 1
    else:
        slider_length = sr.height()
        slider_min = gr.y()
        slider_max = gr.bottom() - slider_length + 1
    pr = pos - sr.center() + sr.topLeft()
    p = pr.x() if widget.orientation() == QtCore.Qt.Horizontal else pr.y()
    return QtWidgets.QStyle.sliderValueFromPosition(widget.minimum(), widget.maximum(), p - slider_min,
                                                    slider_max - slider_min, opt.upsideDown)


class ClickableSlider(QtWidgets.QSlider):

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            val = pixel_pos_to_range_val(self, event.pos())
            self.setValue(val)
        super(ClickableSlider, self).mousePressEvent(event)


class ClickableRangeSlider(QRangeSlider):

    handleSelected = QtCore.Signal(int)
    handleAdded = QtCore.Signal(int)
    handleRemoved = QtCore.Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_value = self.value()

    def mousePressEvent(self, event):
        self._last_value = self.value()
        super(ClickableRangeSlider, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super(ClickableRangeSlider, self).mousePressEvent(event)
        if event.button() != QtCore.Qt.LeftButton:
            return
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers not in (QtCore.Qt.ControlModifier, QtCore.Qt.ShiftModifier):
            return
        val = pixel_pos_to_range_val(self, event.pos())
        new_value = self._last_value
        if modifiers == QtCore.Qt.ControlModifier:
            new_value = sorted(set(list(self._last_value) + [val]))
            self.handleAdded.emit(val)
        elif modifiers == QtCore.Qt.ShiftModifier:
            if len(self.value()) == 1:  # leave at least one marker
                QtWidgets.QMessageBox.critical(self, 'Timeline Markers Error',
                                               'At least one marker needs to be specified')
                return
            # account for user error, they might click close to the handle but not directly on it
            error_margin = self.maximum() * 0.01   # error margin is 1%
            error_margin = ceil(error_margin) if error_margin < 1.0 else floor(error_margin)
            closest_values = [v for v in self._last_value if (val-error_margin) <= v <= (val+error_margin)]
            if closest_values:
                new_value = list(self._last_value)
                new_value.remove(min(closest_values))
                new_value = sorted(set(new_value))
                self.handleRemoved.emit(min(closest_values))
        self.setValue(new_value)

    def mouseDoubleClickEvent(self, event):
        val = pixel_pos_to_range_val(self, event.pos())
        self.handleSelected.emit(val)


class ShotWidget(QtWidgets.QWidget):

    def __init__(self, parent: QtWidgets.QWidget = None, shot_data: utils.ShotData = None):
        super().__init__(parent=parent)

        self._shot_data = shot_data
        self._build_ui()

    def _build_ui(self):
        self._shot_img_lb = QtWidgets.QLabel(self)
        self._shot_img_lb.setPixmap(QtGui.QIcon(self._shot_data.thumbnail.as_posix()).pixmap(80, 80))
        # self._shot_img_lb.resize(pixmap.width(), pixmap.height())

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

    def refresh_shots(self, shot_list: List[utils.ShotData]):
        """
        Refresh list of camera widgets based on sequence/shots cameras

        Returns:
            list[CameraWidget]: list of camera widgets
        """
        self._shot_list = shot_list
        if not shot_list:
            return self.shot_widgets

        for shot_data in sorted(self._shot_list, key=lambda x: str(x.index)):
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

        self.shots = []
        self._full_screen = False
        self._last_pause_state = True
        self._probe_data: utils.FFProbe = None

        self._build_ui()
        self._connect_ui()
        player = mpv.MPV(wid=str(int(self._screen.winId())), keep_open='yes', framedrop='no')

        @player.property_observer('time-pos')
        def time_observer(_, value):
            self._time_observer(value)

        self._player = player

        # FIXME delete bolow, for texting only
        self._src_file_le.setText(Path(r'\\ripley\work\TFT_SET_10\1_PREPROD\03_ANIMATIC\TFTSet10_ANC_Full_230728_shotnumbers.mp4').as_posix())
        self._video_selected()

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

        self.installEventFilter(self)

    def _build_ui(self):
        self._src_file_le = QtWidgets.QLineEdit()
        self._src_file_le.setReadOnly(True)
        self._browse_pb = QtWidgets.QPushButton('Select Map File')
        self._threshold_sp = QtWidgets.QSpinBox()
        self._threshold_sp.wheelEvent = lambda event: None
        self._threshold_sp.setEnabled(False)
        self._threshold_sp.setRange(0, 100)
        self._threshold_sp.setValue(25)
        self._process_pb = QtWidgets.QPushButton('Process')
        self._process_pb.setEnabled(False)
        self._screen = QtWidgets.QFrame()
        self._screen.setMinimumSize(450, 450)
        self._timeline_sl = ClickableSlider(QtCore.Qt.Horizontal)
        self._timeline_sl.setEnabled(False)
        self._marker_timeline_sl = ClickableRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._marker_timeline_sl.setEnabled(False)
        self._zoom_timeline_sl = QRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._zoom_timeline_sl.setEnabled(False)
        self._current_frame_sp = QtWidgets.QSpinBox()
        self._current_frame_sp.wheelEvent = lambda event: None
        self._current_frame_sp.setEnabled(False)
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

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self._src_file_le, 0, 0, 1, 1)
        layout.addWidget(self._browse_pb, 0, 1, 1, 1)
        layout.addWidget(self._threshold_sp, 0, 2, 1, 1)
        layout.addWidget(self._process_pb, 0, 3, 1, 1)
        layout.addWidget(self._screen, 1, 0, 1, 4)
        layout.addWidget(self._player_controls_w, 2, 0, 1, 4)
        layout.addWidget(self._timeline_sl, 3, 0, 1, 3)
        layout.addWidget(self._current_frame_sp, 3, 3, 1, 1)
        layout.addWidget(self._zoom_timeline_sl, 4, 0, 1, 3)
        layout.addWidget(self._marker_timeline_sl, 5, 0, 1, 3)
        layout.addWidget(self._shots_panel_lw, 1, 5, 4, 3)
        self.setLayout(layout)

    def _connect_ui(self):
        self._browse_pb.clicked.connect(self._browse_video)
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
        self._zoom_timeline_sl.sliderReleased.connect(self.update_timeline_focus)
        self._marker_timeline_sl.handleSelected.connect(self._timeline_seek)

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

    def _process_video(self):
        video_path = Path(self._src_file_le.text())
        if not self._player or not video_path.exists():
            return
        self._probe_data = utils.probe_file(video_path, detection_threshold=self._threshold_sp.value())
        if not self._probe_data.shots:
            QtWidgets.QMessageBox.critical(self, 'Detection Error', 'Could not detect any shots in provided video !')
            return
        import pprint
        pprint.pprint(self._probe_data.shots)

        frame_range = (1, self._probe_data.frames)
        self._current_frame_sp.blockSignals(True)
        self._current_frame_sp.setRange(*frame_range)
        for slider in [self._timeline_sl, self._zoom_timeline_sl, self._marker_timeline_sl]:
            slider.blockSignals(True)
            slider.setTickInterval(1)
            slider.setRange(*frame_range)
        self._zoom_timeline_sl.setValue(frame_range)
        markers = [s.start_frame for s in self._probe_data.shots]
        self._marker_timeline_sl.setValue(markers)
        self._shots_panel_lw.refresh_shots(self._probe_data.shots)

        for slider in [self._current_frame_sp, self._timeline_sl, self._zoom_timeline_sl, self._marker_timeline_sl]:
            slider.setEnabled(True)
            slider.blockSignals(False)
        self._player_controls_w.setEnabled(True)

        self._player.loadfile(video_path.as_posix())
        self._player.pause = True

    def update_timeline_focus(self):
        start, end = self._zoom_timeline_sl.value()
        markers = [s.start_frame for s in self._probe_data.shots if s.start_frame >= start and s.end_frame <= end]
        current_frame = self._current_frame_sp.value()
        if not (start <= current_frame <= end):
            self._current_frame_sp.setValue(start if current_frame < start else end)
        self._timeline_sl.setRange(start, end)
        self._marker_timeline_sl.setValue(markers)
        self._marker_timeline_sl.setRange(start, end)

    def _time_observer(self, value: float):
        if not self._probe_data or not value:
            return
        current_frame = utils.seconds_to_frames(value, self._probe_data.fps)
        self._timeline_sl.setValue(int(current_frame))
        self._current_frame_sp.setValue(int(current_frame))
        QtWidgets.QApplication.processEvents()

    def _timeline_seek(self, value: Union[int, float] = None):
        if not self._probe_data:
            return
        value = value if isinstance(value, (int, float)) else self._timeline_sl.value()
        self._player.seek(utils.frames_to_seconds(value, self._probe_data.fps), reference='absolute+exact')
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


