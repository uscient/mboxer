import pytest
from mboxer.config import ConfigError, load_config, get_database_path, get_path, get_setting


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


@pytest.mark.parametrize("value", [False, 0, "", None])
def test_setting_preserves_explicit_falsey_values(value):
    assert get_setting({"ingest": {"max_body_chars": value}}, "ingest.max_body_chars") is value


def test_setting_uses_bundled_defaults_without_merging_config():
    config = {"rules": []}
    assert get_setting(config, "ingest.batch_commit_size") == load_config()["ingest"]["batch_commit_size"]
    assert config == {"rules": []}


def test_mutating_default_setting_does_not_contaminate_future_defaults():
    profiles = get_setting({}, "exports.notebooklm.profiles")
    profiles["ultra_safe"]["max_sources"] = 1
    assert get_setting({}, "exports.notebooklm.profiles")["ultra_safe"]["max_sources"] == 600


def test_unknown_setting_has_no_invented_default():
    with pytest.raises(ConfigError, match="No bundled default"):
        get_setting({}, "unknown.setting")


@pytest.mark.parametrize("configured, override, expected", [
    ({}, None, "var/mboxer.sqlite"),
    ({"project": {"default_database": "legacy.sqlite"}}, None, "legacy.sqlite"),
    ({"paths": {"database": "preferred.sqlite"}, "project": {"default_database": "legacy.sqlite"}},
     None, "preferred.sqlite"),
    ({"paths": {"database": "preferred.sqlite"}}, "override.sqlite", "override.sqlite"),
    ({"paths": {"database": None}, "project": {"default_database": "legacy.sqlite"}},
     None, "legacy.sqlite"),
])
def test_database_path_precedence_and_legacy_compatibility(configured, override, expected):
    assert str(get_database_path(configured, override)) == expected


@pytest.mark.parametrize("configured, override, expected", [
    ({}, None, "exports/notebooklm"),
    ({"paths": {"notebooklm_dir": "custom"}}, None, "custom"),
    ({"paths": {"notebooklm_dir": "custom"}}, "cli", "cli"),
    ({"paths": {"notebooklm_dir": ""}}, None, "exports/notebooklm"),
])
def test_output_path_precedence(configured, override, expected):
    assert str(get_path(configured, "paths.notebooklm_dir", override)) == expected


def test_invalid_path_is_a_clean_config_error():
    with pytest.raises(ConfigError, match="Config path must be a string"):
        get_database_path({"paths": {"database": ["invalid"]}})


@pytest.mark.parametrize("paths, expected", [
    ({}, "data/attachments"),
    ({"attachments_dir": ""}, "."),
    ({"attachments_dir": "saved"}, "saved"),
])
def test_attachment_path_preserves_current_directory(paths, expected):
    assert str(get_path({"paths": paths}, "paths.attachments_dir", fallback_on_empty=False)) == expected


@pytest.mark.parametrize("value", [None, False, 0, []])
def test_invalid_attachment_path_does_not_silently_default(value):
    with pytest.raises(ConfigError, match="Config path must be a string"):
        get_path({"paths": {"attachments_dir": value}}, "paths.attachments_dir", fallback_on_empty=False)
