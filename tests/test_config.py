import pytest
from mboxer.config import ConfigError, load_config, get_database_path


def test_load_config_default():
    config = load_config("config/mboxer.example.yaml")
    assert isinstance(config, dict)
    assert "exports" in config


def test_load_config_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("nonexistent/path.yaml")


def test_get_database_path_override(tmp_path):
    config = load_config("config/mboxer.example.yaml")
    override = str(tmp_path / "custom.sqlite")
    result = get_database_path(config, override)
    assert str(result) == override


def test_get_database_path_from_config():
    config = load_config("config/mboxer.example.yaml")
    result = get_database_path(config, None)
    assert "mboxer.sqlite" in str(result)
