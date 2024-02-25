from __future__ import annotations

from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from opentimelineio import opentime

from wolverine import shots
from wolverine.ui.ui_utils import get_icon, ONE_BILLION


DEFAULT_SHOT_STYLE = '#ShotWidget {border: 1px solid white;}'
SELECTED_SHOT_STYLE = '#ShotWidget {border: 2px solid yellow;}'
SHOT_RANGE_TEXT = '{start:03d} - {end:03d} ({duration:03d})'


class ShotWidget(QtWidgets.QFrame):
    sig_shot_changed = QtCore.Signal(QtWidgets.QFrame)
    sig_shot_selected = QtCore.Signal(QtWidgets.QFrame)
    sig_shot_loop = QtCore.Signal(tuple)
    sig_shot_deleted = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget = None, shot_data: shots.ShotData = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName('ShotWidget')

        self.shot_data: shots.ShotData = shot_data
        self.__updating_ui: bool = False
        self._active = False

        self._build_ui()
        self.fill_from_data(self.shot_data)
        self._connect_ui()

    def _build_ui(self) -> None:
        self._shot_name_lb = QtWidgets.QLabel()
        self._shot_img_lb = QtWidgets.QLabel(self)
        self._range_lb = QtWidgets.QLabel()
        self._range_lb.setStyleSheet('font-size: 10;')

        self._shot_enabled_pb = QtWidgets.QPushButton()
        self._shot_enabled_pb.setIcon(get_icon('enabled.png'))
        self._shot_enabled_pb.setStyleSheet('border : 0;')
        self._shot_enabled_pb.setToolTip('Enable/Disable')
        self._shot_enabled_pb.setFocusPolicy(QtCore.Qt.NoFocus)

        self._shot_ignored_pb = QtWidgets.QPushButton()
        self._shot_ignored_pb.setIcon(get_icon('ignored.png'))
        self._shot_ignored_pb.setStyleSheet('border : 0;')
        self._shot_ignored_pb.setToolTip('Ignore')
        self._shot_ignored_pb.setFocusPolicy(QtCore.Qt.NoFocus)

        self._shot_loop_pb = QtWidgets.QPushButton()
        self._shot_loop_pb.setIcon(get_icon('loop.png'))
        self._shot_loop_pb.setStyleSheet('border : 0;')
        self._shot_loop_pb.setVisible(False)
        self._shot_loop_pb.setToolTip('Loop')
        self._shot_loop_pb.setFocusPolicy(QtCore.Qt.NoFocus)

        self._shot_delete_pb = QtWidgets.QPushButton()
        self._shot_delete_pb.setIcon(get_icon('delete.png'))
        self._shot_delete_pb.setStyleSheet('border : 0;')
        self._shot_delete_pb.setToolTip('Delete')
        self._shot_delete_pb.setFocusPolicy(QtCore.Qt.NoFocus)

        header_lay = QtWidgets.QHBoxLayout()
        header_lay.addWidget(self._shot_enabled_pb)
        header_lay.addWidget(self._shot_ignored_pb)
        header_lay.addWidget(self._shot_loop_pb)
        header_lay.addStretch(3)
        header_lay.addWidget(self._shot_delete_pb)
        header_lay.setContentsMargins(0, 0, 0, 0)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(header_lay)
        layout.addWidget(self._shot_img_lb)
        layout.addWidget(self._shot_name_lb)
        layout.addWidget(self._range_lb)
        layout.setContentsMargins(0, 0, 0, 0)

        self.setLayout(layout)
        self.setMinimumWidth(130)
        self.setMaximumWidth(130)
        self.setMinimumHeight(130)
        self.setMaximumHeight(130)
        self.setStyleSheet(DEFAULT_SHOT_STYLE)

    def _connect_ui(self) -> None:
        self._shot_enabled_pb.clicked.connect(self._toggle_enabled)
        self._shot_ignored_pb.clicked.connect(self._toggle_ignored)
        self._shot_loop_pb.clicked.connect(self._toggle_loop)
        self._shot_delete_pb.clicked.connect(lambda: self.sig_shot_deleted.emit(self.shot_data.start_frame))

    @property
    def name(self):
        return self._shot_name_lb.text()

    @property
    def start(self):
        return self.shot_data.start_frame

    @property
    def end(self):
        return self.shot_data.end_frame

    @property
    def is_active(self):
        return self._active

    @is_active.setter
    def is_active(self, value: bool):
        self._active = value
        self.setStyleSheet(SELECTED_SHOT_STYLE if self._active else DEFAULT_SHOT_STYLE)

    def mousePressEvent(self, QMouseEvent):
        self.is_active = True
        self.sig_shot_selected.emit(self)

    def fill_from_data(self, shot_data: shots.ShotData):
        self.shot_data = shot_data

        self.__updating_ui = True
        self._shot_name_lb.setText(self.shot_data.name)
        self._shot_enabled_pb.setIcon(get_icon('enabled.png' if self.shot_data.enabled else 'disabled.png'))
        self._shot_ignored_pb.setIcon(get_icon('ignored.png' if self.shot_data.ignored else 'not_ignored.png'))
        range_text = SHOT_RANGE_TEXT.format(
            start=int(self.shot_data.start_frame),
            end=int(self.shot_data.end_frame),
            duration=int(self.shot_data.duration)
        )
        self._range_lb.setText(range_text)
        if self.shot_data.thumbnail:
            self._shot_img_lb.setPixmap(QtGui.QIcon(self.shot_data.thumbnail.as_posix()).pixmap(130, 100))
        self.__updating_ui = False

    def _toggle_loop(self):
        if not self.shot_data:
            return
        self.sig_shot_loop.emit((self.shot_data.start_frame, self.shot_data.end_frame))

    def _toggle_enabled(self):
        self.shot_data.enabled = not self.shot_data.enabled
        self.sig_shot_changed.emit(self)

    def _toggle_ignored(self):
        self.shot_data.enabled = not self.shot_data.ignored
        self.sig_shot_changed.emit(self)


class ShotInfoWidget(QtWidgets.QGroupBox):
    sig_range_changed = QtCore.Signal(shots.ShotData, tuple)
    sig_shot_changed = QtCore.Signal()
    sig_shot_loop = QtCore.Signal(tuple)
    sig_shot_deleted = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget = None) -> None:
        super().__init__('Shot Info :', parent=parent)

        self._shot_widget: ShotWidget | None = None
        self._shot_data: shots.ShotData | None = None
        self.__updating_ui: bool = False

        self._build_ui()
        self._connect_ui()

    def _build_ui(self) -> None:
        self._shot_name_lb = QtWidgets.QLabel()
        self._shot_enabled_cb = QtWidgets.QCheckBox('Enabled')
        self._shot_enabled_pb = QtWidgets.QPushButton()
        self._shot_enabled_pb.setIcon(get_icon('enabled.png'))
        self._shot_enabled_pb.setToolTip('Enable/Disable')
        self._shot_ignored_cb = QtWidgets.QCheckBox('Ignored')
        self._shot_ignored_pb = QtWidgets.QPushButton()
        self._shot_ignored_pb.setIcon(get_icon('ignored.png'))
        self._shot_ignored_pb.setToolTip('Ignore')
        self._shot_loop_pb = QtWidgets.QPushButton()
        self._shot_loop_pb.setIcon(get_icon('loop.png'))
        self._shot_loop_pb.setToolTip('Loop')
        self._shot_loop_pb.setVisible(False)
        self._shot_delete_pb = QtWidgets.QPushButton()
        self._shot_delete_pb.setIcon(get_icon('delete.png'))
        self._shot_delete_pb.setToolTip('Delete')

        self._start_sp = QtWidgets.QSpinBox()
        self._end_sp = QtWidgets.QSpinBox()
        self._new_start_sp = QtWidgets.QSpinBox()
        self._duration_sp = QtWidgets.QSpinBox()
        self._new_end_sp = QtWidgets.QSpinBox()

        for widget in [self._start_sp, self._end_sp, self._duration_sp, self._new_start_sp, self._new_end_sp]:
            widget.wheelEvent = lambda event: None
            widget.setRange(0, ONE_BILLION)
        self._end_sp.setRange(1, ONE_BILLION)

        header_lay = QtWidgets.QHBoxLayout()
        header_lay.addWidget(self._shot_name_lb)
        header_lay.addStretch(3)
        header_lay.addWidget(self._shot_enabled_pb)
        header_lay.addWidget(self._shot_ignored_pb)
        header_lay.addWidget(self._shot_loop_pb)
        header_lay.addWidget(self._shot_delete_pb)

        range_lay = QtWidgets.QHBoxLayout()
        range_lay.addWidget(QtWidgets.QLabel('Start'))
        range_lay.addWidget(self._start_sp)
        range_lay.addWidget(QtWidgets.QLabel('Duration'))
        range_lay.addWidget(self._duration_sp)
        range_lay.addWidget(QtWidgets.QLabel('End'))
        range_lay.addWidget(self._end_sp)

        range_info_lay = QtWidgets.QHBoxLayout()
        range_info_lay.addWidget(QtWidgets.QLabel('New Start'))
        range_info_lay.addWidget(self._new_start_sp)
        range_info_lay.addWidget(QtWidgets.QLabel('New End'))
        range_info_lay.addWidget(self._new_end_sp)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(header_lay)
        layout.addLayout(range_lay)
        layout.addLayout(range_info_lay)

        self.setLayout(layout)

    def _connect_ui(self) -> None:
        self._shot_enabled_pb.clicked.connect(self._toggle_enabled)
        self._shot_ignored_pb.clicked.connect(self._toggle_ignored)
        self._shot_loop_pb.clicked.connect(self._toggle_loop)
        self._shot_delete_pb.clicked.connect(self._delete_shot)
        self._start_sp.editingFinished.connect(lambda: self._range_changed('start'))
        self._end_sp.editingFinished.connect(lambda: self._range_changed('end'))
        self._duration_sp.editingFinished.connect(lambda: self._range_changed('duration'))
        self._new_start_sp.editingFinished.connect(lambda: self._range_changed('new_start'))
        self._new_end_sp.editingFinished.connect(lambda: self._range_changed('new_end'))

    def fill_shot_ui(self, shot_widget: ShotWidget):
        if not shot_widget:
            return
        self._shot_widget = shot_widget
        self._shot_data = self._shot_widget.shot_data

        self.__updating_ui = True
        self._shot_name_lb.setText(self._shot_data.name)

        self._shot_enabled_cb.setChecked(self._shot_data.enabled)
        self._shot_enabled_cb.setIcon(get_icon('enabled.png' if self._shot_data.enabled else 'disabled.png'))
        self._shot_ignored_cb.setChecked(self._shot_data.ignored)
        self._shot_ignored_cb.setIcon(get_icon('ignored.png' if self._shot_data.ignored else 'not_ignored.png'))

        self._start_sp.setValue(self._shot_data.start_frame)
        self._end_sp.setValue(self._shot_data.end_frame)
        self._new_start_sp.setValue(self._shot_data.new_start)
        self._duration_sp.setValue(self._shot_data.duration)
        self._new_end_sp.setValue(self._shot_data.new_end)

        self._shot_widget.fill_from_data(self._shot_data)
        self.__updating_ui = False

    def _toggle_loop(self):
        if not self._shot_data:
            return
        self.sig_shot_loop.emit((self._shot_data.start_frame, self._shot_data.end_frame))

    def _toggle_enabled(self):
        if not self._shot_widget:
            return

        new_state = not self._shot_enabled_cb.isChecked()
        self._shot_enabled_cb.setIcon(get_icon('enabled.png' if new_state else 'disabled.png'))
        if self._shot_enabled_cb.isChecked() != new_state:
            self._shot_enabled_cb.setChecked(new_state)
        self._shot_data.enabled = new_state
        self._shot_widget.fill_from_data(self._shot_data)
        self.sig_shot_changed.emit()

    def _toggle_ignored(self):
        if not self._shot_widget:
            return

        new_state = not self._shot_ignored_cb.isChecked()
        self._shot_ignored_cb.setIcon(get_icon('ignored.png' if new_state else 'not_ignored.png'))
        if self._shot_ignored_cb.isChecked() != new_state:
            self._shot_ignored_cb.setChecked(new_state)
        self._shot_data.ignored = new_state
        self._shot_widget.fill_from_data(self._shot_data)
        self.sig_shot_changed.emit()

    def _delete_shot(self):
        if not self._shot_widget or self.__updating_ui:
            return
        self.sig_shot_deleted.emit(self._shot_data.start_frame)

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

        self._shot_data.generate_thumbnail()
        self.fill_shot_ui(self._shot_widget)
        self.sig_range_changed.emit(self._shot_data, prev_range)


class ShotListWidget(QtWidgets.QWidget):
    sig_shot_range_changed = QtCore.Signal(shots.ShotData, tuple)
    sig_shots_changed = QtCore.Signal()
    sig_shot_loop = QtCore.Signal(tuple)
    sig_shot_selected = QtCore.Signal(int)
    sig_shot_deleted = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent=parent)

        self._shot_list: list[shots.ShotData] = []
        self._selected_shot: ShotWidget | None = None
        self.shot_widgets: list[ShotWidget] = []

        self._build_ui()
        self._connect_ui()

    def _build_ui(self):
        self._shots_prefix_le = QtWidgets.QLineEdit()

        self._shots_start_sp = QtWidgets.QSpinBox()
        self._shots_start_sp.wheelEvent = lambda event: None
        self._shots_start_sp.setRange(0, ONE_BILLION)
        self._shots_start_sp.setValue(101)

        self._shot_list_lw = QtWidgets.QWidget()
        self._shot_list_lw.setLayout(FlowLayout())

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidget(self._shot_list_lw)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self._shot_info_w = ShotInfoWidget()

        opts_lay = QtWidgets.QHBoxLayout()
        opts_lay.addWidget(QtWidgets.QLabel('Shots Prefix :'))
        opts_lay.addWidget(self._shots_prefix_le)
        opts_lay.addWidget(QtWidgets.QLabel('Shots Start :'))
        opts_lay.addWidget(self._shots_start_sp)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(opts_lay)
        layout.addWidget(self._scroll)
        layout.addWidget(self._shot_info_w)
        layout.setSpacing(0)
        layout.setMargin(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.setMinimumWidth(450)

    def _connect_ui(self):
        self._shots_prefix_le.editingFinished.connect(self._update_shot_names)
        self._shots_start_sp.valueChanged.connect(self._update_shots_start)
        self._shot_info_w.sig_range_changed.connect(self.sig_shot_range_changed.emit)
        self._shot_info_w.sig_shot_changed.connect(self.sig_shots_changed.emit)
        self._shot_info_w.sig_shot_loop.connect(self.sig_shot_loop.emit)
        self._shot_info_w.sig_shot_deleted.connect(self.sig_shot_deleted.emit)

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
            self._shot_info_w.fill_shot_ui(self._selected_shot)
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
            self._shot_info_w.fill_shot_ui(self._selected_shot)
            self.sig_shots_changed.emit()

    def _shot_selected(self, shot_widget: ShotWidget, emit_signal: bool = True):
        for widget in self.shot_widgets:
            if widget == shot_widget:
                continue
            widget.is_active = False
            # widget.set_active(False)
        self._selected_shot = shot_widget
        self._shot_info_w.fill_shot_ui(shot_widget)
        if emit_signal:
            self.sig_shot_selected.emit(shot_widget.start)

    def select_shot(self, shot_widget: ShotWidget):
        if not self.shot_widgets or shot_widget.is_active:
            return

        shot_widget.is_active = True
        self._shot_selected(shot_widget, emit_signal=False)

    def refresh_shots(self, shot_list: list[shots.ShotData]):
        """
        Refresh list of camera widgets based on sequence/shots cameras

        Returns:
            list[CameraWidget]: list of camera widgets
        """
        self._shot_list = shot_list
        if not shot_list:
            return self.shot_widgets

        shot_widgets = {s.name: s for s in self.shot_widgets}
        self.shot_widgets.clear()
        while self._shot_list_lw.layout().count():
            self._shot_list_lw.layout().takeAt(0)

        for shot_data in sorted(self._shot_list, key=lambda x: str(f'{x.index:06d}')):
            if shot_data.name in shot_widgets:
                shot_widget = shot_widgets[shot_data.name]
                shot_widget.fill_from_data(shot_data)
                del shot_widgets[shot_data.name]
            else:
                shot_widget = ShotWidget(parent=self, shot_data=shot_data)
                shot_widget.sig_shot_changed.connect(self._shot_info_w.fill_shot_ui)
                shot_widget.sig_shot_loop.connect(self.sig_shot_loop.emit)
                shot_widget.sig_shot_selected.connect(self._shot_selected)
                shot_widget.sig_shot_deleted.connect(self.sig_shot_deleted.emit)
            self.shot_widgets.append(shot_widget)
            self._shot_list_lw.layout().addWidget(shot_widget)

        for shot_widget in shot_widgets.values():
            if shot_widget == self._selected_shot:
                self._selected_shot = self.shot_widgets[0] if self.shot_widgets else None
            shot_widget.deleteLater()
        if self._selected_shot:
            self._shot_info_w.fill_shot_ui(self._selected_shot)

        return self.shot_widgets


# from https://github.com/pyside/pyside2-setup/blob/5.15/examples/widgets/layouts/flowlayout.py
class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None):
        super(FlowLayout, self).__init__(parent)

        if parent is not None:
            self.setContentsMargins(QtCore.QMargins(0, 0, 0, 0))

        self._item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]

        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)

        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(QtCore.Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self._do_layout(QtCore.QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()

        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())

        size += QtCore.QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._item_list:
            style = item.widget().style()
            layout_spacing_x = style.layoutSpacing(QtWidgets.QSizePolicy.PushButton,
                                                   QtWidgets.QSizePolicy.PushButton,
                                                   QtCore.Qt.Horizontal)
            layout_spacing_y = style.layoutSpacing(QtWidgets.QSizePolicy.PushButton,
                                                   QtWidgets.QSizePolicy.PushButton,
                                                   QtCore.Qt.Vertical)
            space_x = spacing + layout_spacing_x
            space_y = spacing + layout_spacing_y
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y()

