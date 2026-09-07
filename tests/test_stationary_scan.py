"""Explicit synthetic controller; no hardware sessions in tests."""
import json
import threading
from copy import deepcopy

import numpy as np
import pytest

from hyperlab.acquisition.frame import Frame
from hyperlab.acquisition.session import ScanWriter
from hyperlab.io import load_cube
from hyperlab.spectroscopy.scan import stationary_scan, scan_preflight, validate_recipe


GRID = {'grid_id': 'synthetic-native', 'raw_shape_hw': [2, 3], 'sensor_roi_offset': [0, 0],
        'flip_x': False, 'flip_y': False, 'cfa_pattern': None, 'cfa_pattern_origin': 'sensor'}
RECIPE = {'id': 'synthetic-three', 'states': ['gap-A', 'gap-B', 'gap-C'],
          'exposure_us': [10000, 20000, 10000], 'gain': 0, 'gain_units': 'dB'}


class Adapter:
    def __init__(self, fault=None):
        self.index, self.closed, self.fault = 0, False, fault

    def preflight(self, recipe):
        return {'verified': True, 'identity': 'SYNTHETIC adapter', 'documentation': 'this explicit test fixture',
                'exclusive': True, 'source': 'SYNTHETIC', 'shape': [2, 3], 'dtype': '<u2',
                'spatial_grid': GRID, 'pixel_format': 'Mono12', 'saturation_value': 4095}

    def open(self):
        if self.fault == 'open':
            raise OSError('partly opened fixture')

    def configure(self, recipe):
        self.recipe = recipe

    def set_state(self, state, attempt_id):
        return {'state_id': state, 'acknowledged': self.fault != 'ack', 'token': attempt_id,
                'readback_source': 'SYNTHETIC state feedback'}

    def wait_settled(self, ack, stop):
        return {'settled': True, 'token': ack['token'] + ':settled', 'evidence': 'SYNTHETIC settling measurement',
                'clock_domain': 'device', 'settled_at': 100}

    def capture(self, ack, settled, stop):
        i = self.index
        self.index += 1
        meta = dict(valid=True, buffer_complete=True, state_id=ack['state_id'], state_token=ack['token'],
            exposure_id=f'exposure-{i}', freshness_source='synthetic trigger acknowledgement',
            freshness_method='trigger_token', settling_token=settled['token'], host_monotonic_ns=100,
            session_id='synthetic', stream_epoch=1, sequence=i, frame_id=i, pixel_format='Mono12',
            spatial_grid=GRID, exposure_us=self.recipe['exposure_us'][i], gain=0)
        if i == 1:
            if self.fault == 'stale':
                # Host receipt is later; exposure actually preceded settling.
                meta.update(freshness_method='exposure_clock', exposure_clock='device', exposure_start=90, host_monotonic_ns=110)
            elif self.fault == 'clock_domain':
                meta.update(freshness_method='exposure_clock', exposure_clock='host', exposure_start=110)
            elif self.fault == 'backwards':
                meta['host_monotonic_ns'] = 99
            elif self.fault == 'duplicate':
                meta['frame_id'] = 0
            elif self.fault == 'bad_token':
                meta['settling_token'] = 'previous-state'
            elif self.fault == 'setting':
                meta['exposure_us'] = 10000
            elif self.fault == 'grid':
                meta['spatial_grid'] = dict(GRID, flip_x=True)
        data = np.full((2, 3), i + 1, dtype=np.uint16)
        if i == 1 and self.fault == 'alias':
            data = data.view()
        return Frame(data, meta)

    def close(self):
        self.closed = True
        if self.fault == 'cleanup':
            raise OSError('fixture cleanup failed')


def test_exact_states_durable_and_tied_host_ticks(tmp_path):
    adapter = Adapter()
    result = stationary_scan(adapter, RECIPE, tmp_path/'scan')
    assert result['completed'] and adapter.closed
    assert [result[k] for k in ('captured', 'accepted', 'owned', 'durable')] == [3, 3, 3, 3]
    with load_cube(result['raw_path']) as cube:
        np.testing.assert_array_equal(cube.data, np.broadcast_to([1,2,3], (2,3,3)))
        assert cube.metadata['scan_states'] == RECIPE['states']
        assert cube.wavelengths is None and cube.metadata['scan_recipe_id'] == RECIPE['id']
        assert cube.metadata['exposure_s'] == [.01,.02,.01]
        assert len(cube.metadata['frames']) == 3


@pytest.mark.parametrize('fault,reason', [('stale','precedes settling'), ('clock_domain','clock domains'),
    ('backwards','backwards'), ('duplicate','identifier'), ('bad_token','settling interval'),
    ('setting','readback'), ('grid','spatial grid'), ('alias','Borrowed')])
def test_bad_second_state_preserves_only_valid_prefix(tmp_path, fault, reason):
    adapter = Adapter(fault)
    result = stationary_scan(adapter, RECIPE, tmp_path/fault)
    assert result['partial'] and reason in result['error'] and adapter.closed
    assert result['captured'] == 2 and result['accepted'] == result['durable'] == 1
    with load_cube(result['raw_path']) as cube:
        assert cube.shape == (2,3,1) and cube.metadata['scan_states'] == ['gap-A']
        np.testing.assert_array_equal(cube.data, 1)


def test_cancel_during_settle_retains_prefix_and_releases(tmp_path):
    stop = threading.Event()
    def progress(report):
        if report['phase'] == 'SETTLE' and report['accepted'] == 1:
            stop.set()
    adapter = Adapter()
    result = stationary_scan(adapter, RECIPE, tmp_path/'cancel', stop=stop, progress=progress)
    assert adapter.closed and result['durable'] == 1 and result['partial']
    assert result['failed_phase'] == 'SETTLE'


def test_partial_open_and_cleanup_outcomes_stay_separate(tmp_path):
    adapter = Adapter('open')
    result = stationary_scan(adapter, RECIPE, tmp_path/'open')
    assert adapter.closed and 'partly opened' in result['error'] and result['durable'] == 0
    result = stationary_scan(Adapter('cleanup'), RECIPE, tmp_path/'cleanup')
    assert result['completed'] and result['error'] is None
    assert result['cleanup'][0]['status'] == 'FAIL'


def test_write_failure_retains_accepted_accounting(tmp_path):
    class FaultWriter(ScanWriter):
        def append(self, frame, record):
            if self.meta['frame_count'] == 1:
                raise OSError('state write failed')
            super().append(frame,record)
    result = stationary_scan(Adapter(), RECIPE, tmp_path/'write', writer_factory=FaultWriter)
    assert result['captured'] == result['accepted'] == result['owned'] == 2
    assert result['durable'] == result['unpersisted'] == 1 and result['partial']
    assert 'state write failed' in result['error']


def test_no_controller_cannot_start_or_invent_wavelengths(tmp_path):
    with pytest.raises(ValueError, match='selector is not configured'):
        scan_preflight(None, RECIPE, tmp_path/'none')
    assert not (tmp_path/'none').exists()
    for updates in ({'states':['A','A']}, {'exposure_us':[1,0,1]}, {'gain':float('nan')}):
        with pytest.raises(ValueError):
            validate_recipe(dict(RECIPE, **updates))


def test_repeated_physical_state_retains_steps_and_explicit_row_selection(tmp_path):
    from hyperlab.spectroscopy.scan import select_scan_steps
    recipe = dict(id='SYNTHETIC-ABA',gain=0,gain_units='dB',steps=[
        dict(step_id=step,state_id=state,role='sample',exposure_us=10000,expected_source_band=None)
        for step,state in [('A1','A'),('B1','B'),('A2','A')]])
    result=stationary_scan(Adapter(),recipe,tmp_path/'original')
    with load_cube(result['raw_path']) as cube:
        cube.valid_mask=np.ones(cube.shape,bool);cube.valid_mask[0,0,2]=False
        assert cube.metadata['scan_states']==['A','B','A']
        assert [r['step_id'] for r in cube.metadata['frames']]==['A1','B1','A2']
        selected=select_scan_steps(cube,['B1','A2'],tmp_path/'selected')
        with pytest.raises(ValueError,match='one selected observation'):
            select_scan_steps(cube,['A1','A2'],tmp_path/'invalid')
        assert cube.shape[2]==3
    with load_cube(selected['raw_path']) as cube:
        assert cube.metadata['scan_states']==['B','A']
        np.testing.assert_array_equal(cube.data,np.broadcast_to([2,3],(2,3,2)))
        assert cube.metadata['step_selection']['source_indices']==[1,2]
        assert not cube.valid_mask[0,0,1] and cube.valid_mask[0,0,0]


def test_repeated_partial_step_vectors_match_durable_prefix(tmp_path):
    recipe=dict(RECIPE,steps=[dict(step_id=f'visit-{i}',state_id=state,role='sample',
        exposure_us=exposure,expected_source_band=None) for i,(state,exposure) in enumerate(zip(RECIPE['states'],RECIPE['exposure_us']))])
    result=stationary_scan(Adapter('stale'),recipe,tmp_path/'partial-steps')
    with load_cube(result['raw_path']) as cube:
        assert len(cube.metadata['scan_steps'])==len(cube.metadata['exposure_s'])==cube.shape[2]==1


def test_live_contract_accepts_engineer_evidence_and_distinguishes_transport(tmp_path):
    import hashlib
    class RecordedContractAdapter(Adapter):
        def preflight(self,recipe):
            return dict(super().preflight(recipe),source='LIVE',verified=self.verified,transport=self.transport,control_evidence=self.evidence)
    adapter=RecordedContractAdapter()
    adapter.verified=False
    adapter.transport={'present':False};adapter.evidence={}
    with pytest.raises(ValueError,match='not detected'):scan_preflight(adapter,RECIPE,tmp_path/'none')
    adapter.transport={'present':True,'driver_ready':False}
    with pytest.raises(ValueError,match='driver'):scan_preflight(adapter,RECIPE,tmp_path/'driver')
    adapter.transport['driver_ready']=True
    with pytest.raises(ValueError,match='Unverified command'):scan_preflight(adapter,RECIPE,tmp_path/'semantics')
    adapter.verified=True
    with pytest.raises(ValueError,match='recorded protocol'):scan_preflight(adapter,RECIPE,tmp_path/'missing-record')
    contract=dict(identity='SYNTHETIC adapter',kind='engineer_characterized',**{key:'SYNTHETIC test evidence only' for key in
        ('transport_line_behavior','commands_and_ranges','readback','settling','exposure_freshness','cleanup','observations')})
    path=tmp_path/'fixture-contract.json';path.write_text(json.dumps(contract))
    adapter.evidence=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert scan_preflight(adapter,RECIPE,tmp_path/'eligible')['evidence_check'].startswith('Recorded contract')
    # Host-only ACK from the boundary fixture must still be refused as live proof.
    result=stationary_scan(adapter,RECIPE,tmp_path/'host-token')
    assert 'host operation token' in result['error'] and result['captured']==0
    path.write_text('{}')
    with pytest.raises(ValueError,match='matching hash'):scan_preflight(adapter,RECIPE,tmp_path/'changed')


def test_preflight_grid_is_pinned_before_adapter_configuration(tmp_path):
    class MutableGridAdapter(Adapter):
        def preflight(self, recipe):
            facts = super().preflight(recipe)
            self.grid = facts['spatial_grid'] = deepcopy(GRID)
            return facts

        def configure(self, recipe):
            super().configure(recipe)
            self.grid['flip_x'] = True

        def capture(self, ack, settled, stop):
            frame = super().capture(ack, settled, stop)
            return Frame(frame.data, dict(frame.metadata, spatial_grid=self.grid))

    result = stationary_scan(MutableGridAdapter(), RECIPE, tmp_path/'grid-snapshot')
    assert result['partial'] and 'spatial grid' in result['error']
    assert result['accepted'] == result['durable'] == 0
    assert result['adapter']['spatial_grid'] == GRID


def test_reused_adapter_acknowledgement_keeps_each_original_state(tmp_path):
    class ReusedAcknowledgement(Adapter):
        def set_state(self, state, attempt_id):
            record = super().set_state(state, attempt_id)
            if not hasattr(self, 'acknowledgement'):
                self.acknowledgement = {}
            self.acknowledgement.clear()
            self.acknowledgement.update(record)
            return self.acknowledgement

    result = stationary_scan(ReusedAcknowledgement(), RECIPE, tmp_path/'ack-snapshot')
    assert result['completed'] and result['durable'] == 3
    with load_cube(result['raw_path']) as cube:
        frames = cube.metadata['frames']
        assert [frame['acknowledgement']['state_id'] for frame in frames] == RECIPE['states']
        assert all(frame['state_token'] == frame['acknowledgement']['token'] for frame in frames)
    events = [event for event in result['events'] if event['phase'] == 'ACKNOWLEDGE']
    assert [event['acknowledgement']['state_id'] for event in events] == RECIPE['states']


@pytest.mark.parametrize('fault', ['missing_domain', 'text_ticks', 'different_units', None, 'tied'])
def test_exposure_clock_requires_numeric_ticks_and_shared_domain_units(tmp_path, fault):
    class ClockAdapter(Adapter):
        def wait_settled(self, ack, stop):
            record = super().wait_settled(ack, stop)
            record['clock_units'] = 'ns'
            if fault == 'missing_domain':
                record.pop('clock_domain')
            if fault == 'text_ticks':
                record['settled_at'] = '100'
            return record

        def capture(self, ack, settled, stop):
            frame = super().capture(ack, settled, stop)
            metadata = dict(frame.metadata, freshness_method='exposure_clock', exposure_clock='device',
                            exposure_clock_units='ns', exposure_start=100 if fault == 'tied' else 110)
            if fault == 'missing_domain':
                metadata.pop('exposure_clock')
            if fault == 'text_ticks':
                metadata['exposure_start'] = '90'
            if fault == 'different_units':
                metadata['exposure_clock_units'] = 'us'
            return Frame(frame.data, metadata)

    result = stationary_scan(ClockAdapter(), RECIPE, tmp_path/str(fault))
    if fault in (None, 'tied'):
        assert result['completed'] and result['durable'] == 3
    else:
        assert result['partial'] and 'clock domains' in result['error']
        assert result['accepted'] == result['durable'] == 0


def test_finalization_error_keeps_reopenable_raw_prefix_path(tmp_path):
    class FinalizationFailure(ScanWriter):
        def finish(self, **kwargs):
            super().finish(**kwargs)
            raise OSError('synthetic close acknowledgement failure after durable publication')

    result = stationary_scan(Adapter(), RECIPE, tmp_path/'finalize', writer_factory=FinalizationFailure)
    assert result['partial'] and not result['completed']
    assert result['durable'] == result['accepted'] == 3 and result['unpersisted'] == 0
    assert 'close acknowledgement' in result['persistence_error']
    with load_cube(result['raw_path']) as cube:
        np.testing.assert_array_equal(cube.data, np.broadcast_to([1,2,3], (2,3,3)))
        assert cube.metadata['frame_count'] == 3


@pytest.mark.parametrize('updates', [{'exposure_us':[True,True,True]}, {'gain':False}])
def test_boolean_quantities_are_not_valid_recipe_magnitudes(updates):
    with pytest.raises(ValueError):
        validate_recipe(dict(RECIPE, **updates))


@pytest.mark.parametrize('fault', [None, 'ack'])
def test_final_scan_receipt_failure_preserves_primary_and_durable_data(tmp_path, monkeypatch, fault):
    import hyperlab.spectroscopy.scan as module
    original = module.atomic_json
    def failed_final(path, report):
        if 'ended_at' in report:
            raise OSError('synthetic scan receipt disk failure')
        return original(path, report)
    monkeypatch.setattr(module, 'atomic_json', failed_final)
    adapter = Adapter(fault)
    result = stationary_scan(adapter, RECIPE, tmp_path/'scan')
    assert adapter.closed and result['partial'] and not result['completed']
    assert 'receipt disk failure' in result['receipt_error']
    assert result['durable'] == (3 if fault is None else 0)
    if fault == 'ack':
        assert 'did not acknowledge' in result['error']
    else:
        with load_cube(result['raw_path']) as cube:
            assert cube.metadata['completed'] and cube.shape[2] == 3
