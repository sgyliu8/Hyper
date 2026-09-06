import pytest


@pytest.fixture(autouse=True)
def isolated_user_configuration(monkeypatch, tmp_path):
    """Offline tests never read or overwrite the real user's saved workspace."""
    monkeypatch.setenv('HYPERLAB_CONFIG_DIR', str(tmp_path/'config'))
    monkeypatch.setenv('HYPERLAB_WORKSPACE', str(tmp_path/'workspace'))
