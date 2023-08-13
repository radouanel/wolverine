
import sys
from math import ceil, floor
from pathlib import Path

import mpv
from qt_py_tools.Qt import QtWidgets, QtCore
from superqt import QRangeSlider, QLabeledSlider

from wolverine import utils


VALID_VIDEO_EXT = ['.mov', '.mp4', '.mkv', '.avi']
# TODO get split data from ffmpeg
# TODO split shots
# FIXME prev/next frame sometimes stuck between frames


def pixel_pos_to_range_val(widget, pos):
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


class WolverineUI(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle('Wolverine - Sequence Splitter')

        self.shots = []
        self._full_screen = False
        self._last_pause_state = True
        self._probe_data: utils.FFProbe = None

        self._build_ui()
        self._connect_ui()

        player = mpv.MPV(wid=str(int(self._screen.winId())), keep_open='yes')

        @player.property_observer('time-pos')
        def time_observer(_, value):
            self._time_observer(value)

        self._player = player

        # FIXME delete bolow, for texting only
        self._src_file_le.setText(Path(r'\\ripley\work\TFT_SET_10\1_PREPROD\03_ANIMATIC\TFT_Live Sequence\LIVE_SEQ_A.mp4').as_posix())
        self._video_selected()

    def _build_ui(self):
        self._src_file_le = QtWidgets.QLineEdit()
        self._src_file_le.setReadOnly(True)
        self._browse_pb = QtWidgets.QPushButton('Select Map File')
        self._process_pb = QtWidgets.QPushButton('Process')
        self._process_pb.setEnabled(False)
        self._screen = QtWidgets.QFrame()
        self._screen.setMinimumSize(450, 450)
        self._timeline_sl = ClickableSlider(QtCore.Qt.Horizontal)
        self._timeline_sl.setEnabled(False)
        self._marker_timeline_sl = ClickableRangeSlider(QtCore.Qt.Orientation.Horizontal)
        self._marker_timeline_sl.setEnabled(False)
        self._current_frame_sp = QtWidgets.QSpinBox()
        self._current_frame_sp.wheelEvent = lambda event: None
        self._current_frame_sp.setEnabled(False)
        self._loop_pb = QtWidgets.QPushButton('L')
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

        self._player_controls_w = QtWidgets.QWidget()
        controls_lay = QtWidgets.QHBoxLayout()
        controls_lay.addWidget(self._loop_pb)
        controls_lay.addWidget(self._prev_shot_pb)
        controls_lay.addWidget(self._prev_frame_pb)
        controls_lay.addWidget(self._stop_pb)
        controls_lay.addWidget(self._pause_pb)
        controls_lay.addWidget(self._next_frame_pb)
        controls_lay.addWidget(self._next_shot_pb)
        controls_lay.addWidget(self._mute_pb)
        controls_lay.addWidget(self._volume_sl)
        self._player_controls_w.setLayout(controls_lay)
        self._player_controls_w.setEnabled(False)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self._src_file_le, 0, 0, 1, 2)
        layout.addWidget(self._browse_pb, 0, 2, 1, 1)
        layout.addWidget(self._process_pb, 0, 3, 1, 1)
        layout.addWidget(self._screen, 1, 0, 1, 4)
        layout.addWidget(self._player_controls_w, 2, 1, 1, 2)
        layout.addWidget(self._timeline_sl, 3, 0, 1, 3)
        layout.addWidget(self._current_frame_sp, 3, 3, 1, 1)
        layout.addWidget(self._marker_timeline_sl, 4, 0, 1, 3)
        self.setLayout(layout)

    def _connect_ui(self):
        self._browse_pb.clicked.connect(self._browse_video)
        self._src_file_le.editingFinished.connect(self._video_selected)
        self._process_pb.clicked.connect(self._process_video)
        self._loop_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_L))
        self._prev_shot_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Left))
        self._prev_frame_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Left))
        self._stop_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_S))
        self._pause_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Space))
        self._next_frame_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Right))
        self._next_shot_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_Right))
        self._mute_pb.clicked.connect(lambda: self._player_controls(QtCore.Qt.Key_M))
        self._volume_sl.valueChanged.connect(self._set_player_volume)
        self._timeline_sl.sliderPressed.connect(lambda: self._pause_player(True))
        self._timeline_sl.sliderReleased.connect(self._timeline_seek)
        self._marker_timeline_sl.handleSelected.connect(self._timeline_seek)

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

    def _video_selected(self, video_path=None):
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

    def _process_video(self):
        video_path = Path(self._src_file_le.text())
        if not self._player or not video_path.exists():
            return
        self._probe_data = utils.probe_file(video_path, print_stats=True)
        res = utils.ffmpeg_shot_detection(video_path)
        print(res)
        self._timeline_sl.blockSignals(True)
        self._current_frame_sp.blockSignals(True)
        self._marker_timeline_sl.blockSignals(True)

        self._timeline_sl.setTickInterval(1)
        self._timeline_sl.setRange(1, self._probe_data.frames)
        self._current_frame_sp.setRange(1, self._probe_data.frames)
        self._marker_timeline_sl.setValue((1, 20, 40, 80, self._probe_data.frames))

        self._timeline_sl.blockSignals(False)
        self._current_frame_sp.blockSignals(False)
        self._marker_timeline_sl.blockSignals(False)

        self._player_controls_w.setEnabled(True)
        self._timeline_sl.setEnabled(True)
        self._current_frame_sp.setEnabled(True)
        self._marker_timeline_sl.setEnabled(True)

        self._player.loadfile(video_path.as_posix())
        self._player.pause = True

    def _time_observer(self, value):
        if not self._probe_data or not value:
            return
        current_frame = utils.seconds_to_frames(value, self._probe_data.fps)
        self._timeline_sl.setValue(int(current_frame))
        self._current_frame_sp.setValue(int(current_frame))
        QtWidgets.QApplication.processEvents()

    def _timeline_seek(self, value=None):
        if not self._probe_data:
            return
        value = value if isinstance(value, (int, float)) else self._timeline_sl.value()
        self._player.seek(utils.frames_to_seconds(value, self._probe_data.fps), reference='absolute+exact')
        self._player.pause = self._last_pause_state

    def _pause_player(self, status):
        self._last_pause_state = self._player.pause
        self._player.pause = status

    def _set_player_volume(self, volume):
        self._player.volume = volume

    def _player_controls(self, key):
        if not self._player or not self._probe_data:
            return
        if key == QtCore.Qt.Key_Space:
            self._player.pause = not self._player.pause
            return
        if key == QtCore.Qt.Key_S:
            self._pause_player(True)
            self._timeline_sl.setValue(0)
            self._timeline_seek(0.0)
            return
        elif key == QtCore.Qt.Key_Left:
            self._player.frame_back_step()
            return
        elif key == QtCore.Qt.Key_Right:
            self._player.frame_step()
            return
        elif key == QtCore.Qt.Key_M:
            self._player.mute = not self._player.mute
            return
        elif key == QtCore.Qt.Key_L:
            self._player.loop = not self._player.loop
            return
        elif key == QtCore.Qt.Key_F:
            if self._full_screen:
                self.showNormal()
            else:
                self.showFullScreen()
            self._full_screen = not self._full_screen
            return


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ui = WolverineUI()
    ui.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
    ui.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
    ui.show()
    ui.raise_()

    sys.exit(app.exec_())


