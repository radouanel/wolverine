
from math import ceil, floor
from typing import Type, Union

from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from superqt import QLabeledRangeSlider, QLabeledSlider

from opentimelineio.core import add_method
from opentimelineio import media_linker, schema, adapters, opentime
from opentimelineview import settings, timeline_widget, track_widgets, ruler_widget
from opentimelineview.console import TimelineWidgetItem


ONE_BILLION: int = 10**9


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


class ClickableSlider(QLabeledSlider):

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            val = pixel_pos_to_range_val(self, event.pos())
            self.setValue(val)
        super(ClickableSlider, self).mousePressEvent(event)


class ClickableRangeSlider(QLabeledRangeSlider):

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


class OTIOViewWidget(QtWidgets.QWidget):

    time_slider_clicked = QtCore.Signal(int)
    ruler_pressed = QtCore.Signal(int)
    ruler_moved = QtCore.Signal(int)
    ruler_released = QtCore.Signal(int)
    marker_added = QtCore.Signal(int)
    marker_removed = QtCore.Signal(int)

    def __init__(self, parent=None):
        super(OTIOViewWidget, self).__init__(parent=parent)
        self.setObjectName('OpenTimelineIO Viewer')

        for cls in [track_widgets.TimeSlider, ruler_widget.Ruler, track_widgets.Marker]:
            setattr(cls, 'otio_parent', self)

        self._current_file = None
        # widgets
        self.tracks_widget = QtWidgets.QListWidget(
            parent=self
        )
        self.timeline_widget = timeline_widget.Timeline(
            parent=self
        )
        # hide tab bar
        self.timeline_widget.tabBar().setVisible(False)

        root = QtWidgets.QWidget(parent=self)
        layout = QtWidgets.QVBoxLayout(root)

        splitter = QtWidgets.QSplitter(parent=root)
        splitter.addWidget(self.tracks_widget)
        splitter.addWidget(self.timeline_widget)

        splitter.setSizes([100, 700, 300])

        layout.addWidget(splitter)
        self.setLayout(layout)

        # signals
        self.tracks_widget.itemSelectionChanged.connect(
            self._change_track
        )

        self.setStyleSheet(settings.VIEW_STYLESHEET)

    def load(self, path, hook_function_arguments=None, media_linker_name='', media_linker_arguments=None,
             adapter_arguments=None):
        self._current_file = path
        self.setObjectName('OpenTimelineIO View: "{}"'.format(path))

        media_linker_name = media_linker_name or media_linker.MediaLinkingPolicy.ForceDefaultLinker
        hook_function_arguments = hook_function_arguments or {}
        media_linker_arguments = media_linker_arguments or {}
        adapter_arguments = adapter_arguments or {}

        self.tracks_widget.clear()
        file_contents = adapters.read_from_file(
            path,
            hook_function_argument_map=hook_function_arguments,
            media_linker_name=media_linker_name,
            media_linker_argument_map=media_linker_arguments,
            **adapter_arguments
        )

        if isinstance(file_contents, schema.Timeline):
            self.timeline_widget.set_timeline(file_contents)
            self.tracks_widget.setVisible(False)
        elif isinstance(
            file_contents,
            schema.SerializableCollection
        ):
            for s in file_contents:
                TimelineWidgetItem(s, s.name, self.tracks_widget)
            self.tracks_widget.setVisible(True)
            self.timeline_widget.set_timeline(None)

    def load_timeline(self, timeline: schema.Timeline):
        self.tracks_widget.clear()
        self.timeline_widget.set_timeline(timeline)
        self.tracks_widget.setVisible(False)

    @property
    def composition(self):
        if not self.timeline_widget.currentWidget():
            return
        return self.timeline_widget.currentWidget().scene()

    @property
    def time_slider(self):
        return self.composition._time_slider

    @property
    def ruler(self):
        return self.composition.get_ruler()

    def _change_track(self):
        selection = self.tracks_widget.selectedItems()
        if selection:
            self.timeline_widget.set_timeline(selection[0].timeline)

    def show(self):
        super(OTIOViewWidget, self).show()
        self.timeline_widget.frame_all()


def update_method(cls: type, insert: str='post'):
    def decorator(func):
        def updated_func(*args, **kw):
            if insert == 'pre':
                func(*args, **kw)
            getattr(cls, f'{func.__name__}__swap')(*args, **kw)
            if insert == 'post':
                func(*args, **kw)
        setattr(cls, f'{func.__name__}__swap', getattr(cls, func.__name__))
        setattr(cls, func.__name__, updated_func)
    return decorator


def find_in_parents(widget: QtWidgets.QWidget, parent_class: Type) -> Union[QtWidgets.QWidget, None]:
    last_parent = widget
    while hasattr(last_parent, 'parent') or hasattr(last_parent, 'scene'):
        if hasattr(last_parent, 'parent'):
            last_parent = last_parent.parent()
        else:
            last_parent = last_parent.scene()
        if isinstance(last_parent, parent_class):
            break
    if not isinstance(last_parent, parent_class):
        return
    return last_parent


@update_method(track_widgets.TimeSlider)
def mousePressEvent(self, _):
    # if not hasattr(self, 'otio_parent'):
    #     otio_view = find_in_parents(self, OTIOViewWidget)
    #     setattr(self, 'otio_parent', otio_view)

    if not self.otio_parent:
        return
    self.otio_parent.time_slider_clicked.emit(self.otio_parent.ruler.current_frame())

    # handle/emit marker signals
    modifiers = QtWidgets.QApplication.keyboardModifiers()
    if modifiers not in (QtCore.Qt.ControlModifier, QtCore.Qt.ShiftModifier):
        return

    if modifiers == QtCore.Qt.ControlModifier:
        self.otio_parent.marker_added.emit(self.otio_parent.ruler.current_frame())
    elif modifiers == QtCore.Qt.ShiftModifier:
        self.otio_parent.marker_removed.emit(self.otio_parent.ruler.current_frame())


@add_method(track_widgets.Marker)
def mouseMoveEvent(self, mouse_event):
    super(track_widgets.Marker, self).mouseMoveEvent(mouse_event)

    if not self.otio_parent:
        return

    # add ruler and move it with mouse
    if not hasattr(self, 'temp_ruler') or not self.temp_ruler:
        # create new/temp ruler and let otio ui handle creation
        setattr(self, 'temp_ruler', self.otio_parent.composition._add_ruler())
        # set ruler color
        self.temp_ruler.setBrush(QtGui.QBrush(QtGui.QColor(50, 20, 255, 255)))
        # reset time slider ruler which was overriden when creating temp ruler
        self.otio_parent.time_slider.add_ruler(self.otio_parent.ruler)

    pos = self.mapToScene(mouse_event.pos())
    pos = max(pos.x() - track_widgets.CURRENT_ZOOM_LEVEL * track_widgets.TRACK_NAME_WIDGET_WIDTH, 0)
    self.temp_ruler.setPos(QtCore.QPointF(pos, track_widgets.TIME_SLIDER_HEIGHT - track_widgets.MARKER_SIZE))
    self.temp_ruler.update_frame()

    # if not hasattr(self, 'temp_marker'):
    #     setattr(self, 'temp_marker', track_widgets.Marker(self.item.deepcopy(), None))
    #     self.temp_marker.setParentItem(self.otio_parent.time_slider)
    #     self.temp_marker.item.color = 'BLUE'
    #
    # pos = self.mapToScene(mouse_event.pos())
    # pos = max(pos.x() - track_widgets.CURRENT_ZOOM_LEVEL * track_widgets.TRACK_NAME_WIDGET_WIDTH, 0)
    #
    # marker = self.temp_marker
    # marker.setX(pos)
    # marker.setY(self.pos().y())
    # marker.setParentItem(self.otio_parent.time_slider)
    # marker.counteract_zoom()


@add_method(track_widgets.Marker)
def mouseReleaseEvent(self, mouse_event):
    super(track_widgets.Marker, self).mouseReleaseEvent(mouse_event)

    if not self.otio_parent:
        return

    if hasattr(self, 'temp_ruler') and self.temp_ruler:
        self.otio_parent.marker_added.emit(self.temp_ruler.current_frame())
        self.otio_parent.composition.removeItem(self.temp_ruler)
        self.temp_ruler = None
        return

    if QtWidgets.QApplication.keyboardModifiers() == QtCore.Qt.ShiftModifier:
        self.otio_parent.marker_removed.emit(self.otio_parent.ruler.current_frame())


@add_method(ruler_widget.Ruler)
def mousePressEvent(self, mouse_event):
    super(ruler_widget.Ruler, self).mousePressEvent(mouse_event)
    if self.otio_parent:
        self.otio_parent.ruler_pressed.emit(self.current_frame())


@update_method(ruler_widget.Ruler)
def mouseMoveEvent(self, _):
    if self.otio_parent:
        self.otio_parent.ruler_moved.emit(self.current_frame())


@update_method(ruler_widget.Ruler)
def mouseReleaseEvent(self, _):
    if self.otio_parent:
        self.otio_parent.ruler_released.emit(self.current_frame())


@add_method(ruler_widget.Ruler)
def current_frame(self) -> int:
    cur_frame = -1
    for tw, frameNumber_tail, frameNumber_head in self.labels:
        cur_frame = frameNumber_head.frameNumber.text() or frameNumber_tail.frameNumber.text()
        if cur_frame:
            break
    return int(cur_frame)


@add_method(ruler_widget.Ruler)
def map_from_time_space(self, frame):
    if frame == self.current_frame():
        return None, None

    pos = None
    clip_item = None
    for track_item in self.composition.items():
        if not isinstance(track_item, track_widgets.Track):
            continue
        for item in track_item.childItems():
            if not isinstance(item, (track_widgets.ClipItem, track_widgets.NestedItem)):
                continue
            trimmed_range = item.item.trimmed_range()
            duration = trimmed_range.duration.value
            start_time = trimmed_range.start_time.value
            if not start_time <= frame <= start_time + duration:
                continue
            ratio = abs(float(frame) - start_time) / duration
            width = float(item.rect().width())
            potential_pos = ((ratio * width) -
                             ((track_widgets.CURRENT_ZOOM_LEVEL * track_widgets.TRACK_NAME_WIDGET_WIDTH) - item.x()))
            pos = QtCore.QPointF(abs(potential_pos), (track_widgets.TIME_SLIDER_HEIGHT - track_widgets.MARKER_SIZE))
            clip_item = item.item
            break
    return pos, clip_item


@add_method(ruler_widget.Ruler)
def move_to_frame(self, frame):
    pos, clip_item = self.map_from_time_space(frame)
    if not pos:
        return
    self.setPos(pos)
    self.update_frame(clip_item.trimmed_range())

