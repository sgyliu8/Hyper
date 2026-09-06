"""Compact raw-coordinate geometry editor; no change to the source pixels."""
from copy import deepcopy
from PySide6 import QtWidgets as W


def edit_regions(window):
    if window.cube is None:
        return
    dialog = W.QDialog(window); dialog.setWindowTitle('ROI geometry and role')
    dialog.setObjectName('roi_bounds_dialog'); dialog.resize(470, 460)
    form = W.QFormLayout(dialog)
    target = W.QComboBox(); target.setObjectName('roi_bounds_target')
    for record in window.regions():
        target.addItem(record['name'], record['roi_id'])
    form.addRow('ROI', target)
    identity = W.QLabel(); identity.setWordWrap(True); form.addRow(identity)
    role = W.QComboBox(); role.addItems(['reference', 'target', 'exclude']); form.addRow('Role', role)
    bounds = []
    h,w = window.cube.shape[:2]
    for name,maximum in (('x0',w-1),('y0',h-1),('x1',w),('y1',h)):
        spin = W.QSpinBox(); spin.setRange(0, maximum); spin.setObjectName('roi_bound_'+name)
        form.addRow(name, spin); bounds.append(spin)
    points = W.QPlainTextEdit(); points.setPlaceholderText('One raw x, y point per line')
    form.addRow('Vertices / path', points)
    holes = W.QPlainTextEdit(); holes.setPlaceholderText('One x, y per line; blank line separates holes')
    form.addRow('Polygon holes', holes)
    width = W.QDoubleSpinBox(); width.setRange(.01, 100000); width.setSuffix(' px'); form.addRow('Strip width', width)
    message = W.QLabel('Pixel centres; raw coordinates. Exclude roles subtract from every included ROI.')
    message.setObjectName('roi_bounds_message')
    message.setWordWrap(True); form.addRow(message)
    def selected_roi():
        if window.cube is None or window.cube.shape[:2] != (h,w):
            raise ValueError('Source dimensions changed; reopen the ROI editor.')
        selected = target.currentData()
        for index, record in enumerate(window.regions()):
            if record['roi_id'] == selected:
                return index, record
        raise ValueError('The selected ROI no longer exists; reopen the ROI editor.')
    def refresh_targets(selected):
        target.blockSignals(True); target.clear()
        for record in window.regions():
            target.addItem(record['name'], record['roi_id'])
        target.setCurrentIndex(target.findData(selected)); target.blockSignals(False)
    def show_field(field, visible):
        field.setVisible(visible); form.labelForField(field).setVisible(visible)
    def load(index):
        from hyperlab.analysis.regions import resolve_roi
        try:
            _, record = selected_roi()
            bbox = resolve_roi(window.cube.shape, record)['bbox']
        except (ValueError, OSError) as error:
            message.setText(str(error)); return
        geometry = record['geometry']; kind = geometry['type']
        identity.setText(f"{kind.capitalize()} · revision {record['revision']}")
        identity.setToolTip(record['roi_id']); role.setCurrentText(record['role'])
        for spin,value in zip(bounds, bbox):
            spin.setValue(value); show_field(spin,kind == 'rectangle')
        show_field(points, kind in ('polygon','strip')); show_field(holes, kind == 'polygon')
        show_field(width, kind == 'strip')
        points.setPlainText('\n'.join(f'{x:g}, {y:g}' for x,y in geometry.get('vertices',geometry.get('points',[]))))
        holes.setPlainText('\n\n'.join('\n'.join(f'{x:g}, {y:g}' for x,y in ring) for ring in geometry.get('holes',[])))
        width.setValue(geometry.get('width_px',10))
        if kind == 'mask':
            identity.setText('Verified binary mask · ' + geometry['path'])
    target.currentIndexChanged.connect(load); load(0)
    def parse(text):
        return [[float(value) for value in line.replace(',', ' ').split()] for line in text.splitlines() if line.strip()]
    def apply():
        from hyperlab.analysis.regions import make_roi, resolve_roi
        try:
            index, record = selected_roi(); record = deepcopy(record); geometry = record['geometry']
            if geometry['type'] == 'rectangle':
                geometry['bounds'] = [spin.value() for spin in bounds]
            elif geometry['type'] == 'polygon':
                geometry.update(vertices=parse(points.toPlainText()), holes=[parse(ring) for ring in holes.toPlainText().strip().split('\n\n') if ring.strip()])
            elif geometry['type'] == 'strip':
                geometry.update(points=parse(points.toPlainText()), width_px=width.value())
            record.update(role=role.currentText(), revision=record['revision']+1)
            checked = make_roi(window.cube.shape[:2], geometry, **{key:record[key] for key in
                ('name','color','role','roi_id','revision','visible','included')})
            resolve_roi(window.cube.shape, checked)
            window.roi_records[index] = checked
            window.rebuild_roi_graphics()
            if checked['role'] == 'reference':
                window.set_reference_roi(checked['roi_id'])
            elif window.reference_roi_id == checked['roi_id']:
                window.set_reference_roi(None)
            else:
                window.roi_changed()
            refresh_targets(checked['roi_id'])
            message.setText('Applied to the analysis definition; source data is unchanged.')
        except (ValueError, OSError) as error:
            message.setText(str(error))
    row = W.QHBoxLayout()
    for text,step in [('Move up',-1),('Move down',1)]:
        button = W.QPushButton(text); row.addWidget(button)
        def move(checked=False, delta=step):
            try:
                index, record = selected_roi()
            except (ValueError, OSError) as error:
                message.setText(str(error)); return
            other=index+delta
            if not 0 <= other < len(window.roi_names):
                return
            window.reorder_roi(index, other)
            refresh_targets(record['roi_id']); load(target.currentIndex())
        button.clicked.connect(move)
    form.addRow(row)
    buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Apply | W.QDialogButtonBox.StandardButton.Close)
    buttons.button(W.QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
    buttons.rejected.connect(dialog.reject); form.addRow(buttons)
    window._roi_bounds_dialog = dialog; dialog.show()
