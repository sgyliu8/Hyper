"""Display-only clipping retains exact completed analysis and brush receipts."""
from copy import deepcopy

import numpy as np
from test_map_brush_context import mapped


def test_robust_and_shared_limits_do_not_recompute_or_clear_completed_brush(mapped,qtbot):
    mapped.brush_low.setValue(0); mapped.brush_high.setValue(1000)
    mapped.apply_map_brush()
    qtbot.waitUntil(lambda:not mapped.task_busy,timeout=10000)
    distributions=mapped.map_distributions
    right=mapped.right_spec
    brush=mapped.map_brushes[0]
    before=deepcopy(brush['metadata']); mask=brush['mask'].copy()
    image=mapped.map_spec.image.copy(); validity=mapped.map_spec.valid_mask.copy()
    previous=mapped.map_spec; old_record=deepcopy(previous.record())
    mapped.robust_map_limits.setChecked(True)
    assert not mapped.task_busy
    assert mapped.map_distributions is distributions and mapped.right_spec is right
    assert mapped.map_brushes == [brush] and brush['metadata']==before
    np.testing.assert_equal(brush['mask'],mask)
    np.testing.assert_equal(mapped.map_spec.image,image)
    np.testing.assert_equal(mapped.map_spec.valid_mask,validity)
    assert previous.record()==old_record
    mapped.lock_map_limits.setChecked(False)
    assert mapped.map_distributions is distributions and mapped.map_brushes == [brush]
