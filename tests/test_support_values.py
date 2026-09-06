import json

from hyperlab.support import redacted_report


def test_support_filters_values_as_well_as_keys():
    private = 'PRIVATE_BOUNDARY_SENTINEL'
    report = redacted_report({'state': private, 'phases': [{'phase': private,
        'status': private, 'exception_type': private, 'deadline_exceeded': private}]})
    assert private not in json.dumps(report)
    assert report['device_state'] == 'UNKNOWN'
    assert report['phases'] == [{'phase': 'UNKNOWN', 'status': 'UNKNOWN',
        'exception_type': 'UNKNOWN', 'deadline_exceeded': None}]
    assert report['transmitted'] is False


def test_support_retains_known_outcome_without_exception_text():
    report = redacted_report({'state': 'error', 'phases': [{'phase': 'open',
        'status': 'FAILED', 'exception_type': 'TimeoutError',
        'deadline_exceeded': True, 'error': r'C:\Private\camera-serial'}]})
    assert report['device_state'] == 'error'
    assert report['phases'] == [{'phase': 'open', 'status': 'FAILED',
        'exception_type': 'TimeoutError', 'deadline_exceeded': True}]
    assert 'Private' not in json.dumps(report)


def test_support_does_not_trust_an_arbitrary_exception_class_name():
    report = redacted_report({'state': ['streaming'], 'phases': [{'phase': {},
        'exception_type': 'PrivateCustomerProjectError', 'deadline_exceeded': 1}]})
    assert report['device_state'] == 'UNKNOWN'
    assert report['phases'][0]['exception_type'] == 'UNKNOWN'
    assert report['phases'][0]['deadline_exceeded'] is None
