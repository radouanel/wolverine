from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from qt_py_tools.Qt import QtWidgets, QtCore, QtGui
from superqt import QCollapsible


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

