from math import ceil, floor

from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from superqt import QLabeledRangeSlider, QLabeledSlider

from opentimelineio import media_linker, schema, adapters
from opentimelineview import settings, timeline_widget
from opentimelineview.console import TimelineWidgetItem


ONE_BILLION = 10**9  # type: int


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


from opentimelineio.core import add_method
from opentimelineview import track_widgets
from opentimelineview.ruler_widget import Ruler


def update_method(cls, insert='post'):
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


# TODO push fix for media/trimmed timespace
# TODO events to get : Marker moved, Ruler moving + moved
# TODO function to add : marker add, marker remove, ruler move
# TODO remove tracks tab thingy, filter out audio, flatten video tracks
# TODO maybe split all external timeline files (otio, edl, etc...) into two timeline, one that corresponds to the
#  actual file, the other file which is flattened by wolverine using (use otiotool.flatten_timeline) ?


@update_method(track_widgets.TimeSlider, 'post')
def mousePressEvent(self, mouse_event):
    print('TimeSlider mousePressEvent here !')


@add_method(Ruler)
def map_from_time_space(self, frame):
    # HOW TO USE :
    # wanted_frame = 300
    # self._ruler.setPos(self._ruler.map_from_time_space(wanted_frame))
    # self._ruler.update_frame()
    # TODO better search, I think we can traverse the items faster to get the one we need
    # TODO instead of call update_frames (which is slow), update the frame label ourselves since we already have it
    pos = None
    for track_item in self.composition.items():
        if not isinstance(track_item, track_widgets.Track):
            continue
        for item in track_item.childItems():
            if not (isinstance(item, track_widgets.ClipItem) or
                    isinstance(item, track_widgets.NestedItem)):
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
            break
    return pos


@update_method(Ruler)
def mouseMoveEvent(self, mouse_event):
    print('Ruler mouse_event.pos() ===> ', mouse_event.pos())
    pos = self.mapToScene(mouse_event.pos())
    print('Ruler pos ===> ', pos)
    print('Ruler mouseMoveEvent here !')


@add_method(track_widgets.Marker)
def mouseMoveEvent(self, mouse_event):
    print('Marker mouse_event.pos() ===> ', mouse_event.pos())
    pos = self.mapToScene(mouse_event.pos())
    print('Marker pos ===> ', pos)
    print('Marker mouseMoveEvent !')

    super(track_widgets.Marker, self).mouseMoveEvent(mouse_event)


class OTIOViewWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(OTIOViewWidget, self).__init__(parent=parent)
        self.setObjectName('OpenTimelineIO Viewer')

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
        self.timeline_widget.selection_changed.connect(
            self._selection_changed
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

    def _change_track(self):
        selection = self.tracks_widget.selectedItems()
        if selection:
            self.timeline_widget.set_timeline(selection[0].timeline)

    def _selection_changed(self, item):
        print('OTIO Selected Item : ', item)

    def show(self):
        super(OTIOViewWidget, self).show()
        self.timeline_widget.frame_all()