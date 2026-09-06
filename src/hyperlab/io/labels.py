"""Display names without changing the stored signal domain or metadata."""
from numbers import Integral


def display_labels(metadata, feature_count):
    if isinstance(feature_count, bool) or not isinstance(feature_count, Integral) or feature_count < 1:
        raise ValueError('Display labels require a positive feature count')
    labels = metadata.get('channel_labels')
    if labels is not None:
        if (not isinstance(labels, (list, tuple)) or len(labels) != feature_count or
                any(not isinstance(label, str) or not label.strip() for label in labels)):
            raise ValueError('Explicit channel labels must be nonempty strings matching the stored feature count')
        return list(labels)
    wavelengths, units = metadata.get('wavelengths'), metadata.get('wavelength_units')
    if wavelengths is not None and units and len(wavelengths) == feature_count:
        return [f'{value:g} {units}' for value in wavelengths]
    if feature_count == 1 and (metadata.get('data_level') in ('raw_frame', 'derived_frame') or
                               metadata.get('axis_label') == 'sensor_plane'):
        return ['Sensor plane']
    kind = 'State' if metadata.get('data_level') == 'raw_scan' else 'Feature'
    return [f'{kind} {index}' for index in range(feature_count)]
