"""Small persisted workbench state; it never connects hardware on restore."""
from pathlib import Path
from PySide6 import QtCore
from hyperlab.paths import load_config, save_config


def save_state(window):
    config = load_config()
    cube = window.cube
    previous = config.get('ui', {})
    last_path = str(window.sequence.path) if window.sequence else (
        cube.metadata.get('source_file') if cube is not None else previous.get('last_path'))
    state = {'last_path':last_path,
             'synthetic':cube is not None and cube.metadata.get('data_source') == 'SYNTHETIC' and not last_path,
             'geometry':bytes(window.saveGeometry().toBase64()).decode('ascii'),
             'view_range':window.plot.getViewBox().viewRange(),
             'band':window.band.value(), 'tab':window.tabs.currentIndex(),
             'auto_levels':window.auto_levels.isChecked(), 'levels':list(window.levels or (0,1)),
             'policy':window.policy.currentData(), 'shape_normalize':window.shape_normalize.isChecked(),
             'spatial_sd':window.spatial_sd.isChecked(),
             'rois':[{'name':window.roi_names[i].text(), 'rect':list(rect), 'color':window.roi_colors[i],
                      'visible':window.roi_visible[i].isChecked()} for i,rect in enumerate(window.rectangles())] if cube else previous.get('rois',[]),
             'references':[window.references.item(i).data(QtCore.Qt.ItemDataRole.UserRole)
                           for i in range(window.references.count())],
             'recent':[{'path':window.recent_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole),
                        'relocation':window.recent_list.item(i).data(QtCore.Qt.ItemDataRole.UserRole+1),
                        'partial':window.recent_list.item(i).text().startswith('PARTIAL')}
                       for i in range(window.recent_list.count())]}
    config.update(workspace=str(window.workspace), ui=state, device_profile=window.profile)
    save_config(config)


def restore_controls(window, state):
    if state.get('geometry'):
        window.restoreGeometry(QtCore.QByteArray.fromBase64(state['geometry'].encode('ascii')))
    window.tabs.setCurrentIndex(min(2, max(0, state.get('tab',0))))
    window.policy.setCurrentIndex(1 if state.get('policy') == 'quantitative' else 0)
    window.shape_normalize.setChecked(bool(state.get('shape_normalize')))
    window.spatial_sd.setChecked(state.get('spatial_sd',True))
    window.auto_levels.setChecked(state.get('auto_levels',True))
    for control,value in zip((window.low,window.high),state.get('levels',[0,4095])):
        control.setValue(value)
    for reference in state.get('references',[]):
        window._reference_added(reference)
    for item in reversed(state.get('recent',[])):
        window.add_recent(Path(item['path']), partial=item.get('partial',False))
        window.recent_list.item(0).setData(QtCore.Qt.ItemDataRole.UserRole+1,item.get('relocation'))


def restore_view(window):
    state = window._pending_state
    if not state or window.cube is None:
        return
    window._pending_state = None
    if state.get('last_path') and not window.sequence and window.cube.metadata.get('source_file') != state['last_path']:
        return  # Geometry belongs to the saved source, not an unrelated file.
    if state.get('rois'):
        for roi in [*window.rois,*window.roi_labels]:
            window.plot.removeItem(roi)
        for row in window.roi_rows:
            row.setParent(None); row.deleteLater()
        window.rois,window.roi_labels,window.roi_rows = [],[],[]
        window.roi_names,window.roi_colors,window.roi_visible = [],[],[]
        h,w = window.cube.shape[:2]
        for item in state['rois'][:8]:
            x0,y0,x1,y1 = item['rect']
            if 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h:
                window.add_roi(item['name'],item['rect'],item['color'])
                window.roi_visible[-1].setChecked(item.get('visible',True))
        if not window.rois:
            window.add_roi()
    window.band.setValue(min(window.band.maximum(),state.get('band',0)))
    if state.get('view_range'):
        x,y = state['view_range']
        window.plot.setRange(xRange=x,yRange=y,padding=0)
