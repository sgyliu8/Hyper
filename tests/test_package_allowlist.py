import importlib.util
from pathlib import Path
import stat
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_files', ROOT/'packaging/public_files.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.mark.parametrize('extra', ['local/raw.npy', 'docs/dev/review.md', 'src/hyperlab/resources/private.json',
                                  'HyperLab/_internal/extra.dll', '../escape', '/absolute', 'C:/owner', 'a\\b'])
def test_unapproved_members_fail_without_echoing_names(extra):
    with pytest.raises(ValueError) as error:
        package.check_names(['approved', extra], {'approved'})
    assert extra not in str(error.value)


@pytest.mark.parametrize('entries', [['approved', 'approved'], ['approved', 'Approved'], []])
def test_duplicates_and_missing_members_fail(entries):
    with pytest.raises(ValueError):
        package.check_names(entries, {'approved'})


def test_real_zip_rejects_symlink_and_case_collision(tmp_path):
    path = tmp_path/'distribution.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        link = zipfile.ZipInfo('approved')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, '../outside')
    with pytest.raises(ValueError, match='Symlinks'):
        package.check_zip(path, {'approved'})
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('HyperLab/approved', 'value')
    assert package.check_zip(path, {'approved'}, prefix='HyperLab/')['members'] == 1


def test_reviewed_source_and_runtime_boundaries():
    source = package.read_allowlist(ROOT/'packaging/public_files.txt')
    frozen = package.read_allowlist(ROOT/'packaging/frozen_members.txt')
    assert all((ROOT/name).is_file() for name in source)
    assert not any(name.startswith(('local/', 'docs/dev/')) for name in source)
    assert 'src/hyperlab/resources/hyperlab-logo.png' in source
    assert '_internal/hyperlab/resources/hyperlab-logo.png' in frozen
    assert 'THIRD_PARTY_NOTICES.md' in frozen
    wheel = package.wheel_members(source, '0.6.0')
    assert 'hyperlab/resources/hyperlab-logo.png' in wheel
    assert not any(name.startswith(('docs/', 'tests/', 'packaging/')) for name in wheel)


@pytest.mark.parametrize('name', ['PRIVATE_PROJECT/', 'HyperLab/private/'])
def test_unapproved_empty_zip_directories_are_rejected(tmp_path, name):
    path = tmp_path/'distribution.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('HyperLab/', '')
        archive.writestr('HyperLab/approved', 'value')
        archive.writestr(name, '')
    with pytest.raises(ValueError, match='directory') as error:
        package.check_zip(path, {'approved'}, prefix='HyperLab/')
    assert name not in str(error.value)


def test_unapproved_empty_disk_directory_is_rejected(tmp_path):
    (tmp_path/'approved').write_text('value')
    assert package.check_directory(tmp_path, {'approved'})['status'] == 'PASS'
    (tmp_path/'private').mkdir()
    with pytest.raises(ValueError, match='directory'):
        package.check_directory(tmp_path, {'approved'})
