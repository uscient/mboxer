import pytest
from mboxer.config import ConfigError, load_config, get_database_path


def test_load_config_default_from_unrelated_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert isinstance(config, dict)
    assert "exports" in config


def test_local_example_preserves_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "config" / "mboxer.example.yaml"
    local.parent.mkdir()
    local.write_text("paths:\n  database: local.sqlite\n", encoding="utf-8")
    assert str(get_database_path(load_config())) == "local.sqlite"


def test_explicit_config_preserves_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "config" / "mboxer.example.yaml"
    local.parent.mkdir()
    local.write_text("paths:\n  database: legacy.sqlite\n", encoding="utf-8")
    explicit = tmp_path / "chosen.yaml"
    explicit.write_text("paths:\n  database: explicit.sqlite\n", encoding="utf-8")
    assert str(get_database_path(load_config(explicit))) == "explicit.sqlite"


@pytest.mark.parametrize("contents", ["- not-a-mapping\n", "0", "false"])
def test_config_root_must_be_mapping(tmp_path, contents):
    path = tmp_path / "invalid.yaml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(path)


def test_invalid_yaml_does_not_expose_values(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text("private-value: [sensitive-example", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML") as caught:
        load_config(path)
    assert "sensitive-example" not in str(caught.value)


def test_config_example_prints_bundled_yaml_without_runtime_files(tmp_path, monkeypatch, run_cli):
    import yaml

    monkeypatch.chdir(tmp_path)
    result = run_cli("config-example")
    assert result.exit_code == 0
    assert yaml.safe_load(result.stdout) == load_config()
    assert list(tmp_path.iterdir()) == []


def test_load_config_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("nonexistent/path.yaml")


def test_get_database_path_override(tmp_path):
    config = load_config()
    override = str(tmp_path / "custom.sqlite")
    result = get_database_path(config, override)
    assert str(result) == override


def test_get_database_path_from_config():
    config = load_config()
    result = get_database_path(config, None)
    assert "mboxer.sqlite" in str(result)
