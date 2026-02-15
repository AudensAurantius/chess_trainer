"""Tests for the TOML configuration system."""

import tomllib

import pytest

from src.config import (
    AppConfig,
    ExperimentalConfig,
    OwnGameEvalConfig,
    _apply_env,
    _apply_toml,
    _check_permissions,
    _secure_file,
    _serialize_toml,
    _validate_value,
    coerce_value,
    generate_default_config,
    get_config_keys,
    get_config_value,
    is_experimental_enabled,
    load_config,
    reset_config_value,
    set_config_value,
)


class TestAppConfigDefaults:
    """Tests for default configuration values."""

    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.database.path.endswith("trainer.db")
        assert cfg.lichess.api_url == "https://lichess.org/api"
        assert cfg.lichess.token is None
        assert cfg.scheduler.request_retention == 0.9
        assert cfg.training.max_new_cards == 20
        assert cfg.training.max_reviews == 100
        assert cfg.logging.level == "INFO"
        assert cfg.web.host == "127.0.0.1"
        assert cfg.web.port == 8000


class TestApplyToml:
    """Tests for TOML data overlay."""

    def test_apply_partial_toml(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"training": {"max_new_cards": 50}})
        assert cfg.training.max_new_cards == 50
        # Other values unchanged
        assert cfg.training.max_reviews == 100

    def test_apply_database_path_expands_home(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"database": {"path": "~/my.db"}})
        assert "~" not in cfg.database.path
        assert cfg.database.path.endswith("my.db")

    def test_apply_all_sections(self):
        cfg = AppConfig()
        data = {
            "database": {"path": "/tmp/test.db"},
            "lichess": {"api_url": "http://localhost", "token": "tok"},
            "scheduler": {"request_retention": 0.8, "learning_steps": [1, 5]},
            "training": {"max_new_cards": 10, "interleave_new": False},
            "logging": {"level": "debug"},
            "web": {"host": "0.0.0.0", "port": 9000},
        }
        _apply_toml(cfg, data)
        assert cfg.database.path == "/tmp/test.db"
        assert cfg.lichess.api_url == "http://localhost"
        assert cfg.lichess.token == "tok"
        assert cfg.scheduler.request_retention == 0.8
        assert cfg.scheduler.learning_steps == [1, 5]
        assert cfg.training.max_new_cards == 10
        assert cfg.training.interleave_new is False
        assert cfg.logging.level == "DEBUG"
        assert cfg.web.host == "0.0.0.0"
        assert cfg.web.port == 9000


class TestApplyEnv:
    """Tests for environment variable overrides."""

    def test_env_db_path(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_DB_PATH", "/tmp/env.db")
        _apply_env(cfg)
        assert cfg.database.path == "/tmp/env.db"

    def test_env_lichess_token(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.delenv("LICHESS_TOKEN", raising=False)
        monkeypatch.setenv("CHESS_TRAINER_LICHESS_TOKEN", "my_token")
        _apply_env(cfg)
        assert cfg.lichess.token == "my_token"

    def test_env_legacy_lichess_token(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.delenv("CHESS_TRAINER_LICHESS_TOKEN", raising=False)
        monkeypatch.setenv("LICHESS_TOKEN", "legacy_token")
        _apply_env(cfg)
        assert cfg.lichess.token == "legacy_token"

    def test_env_log_level(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_LOG_LEVEL", "debug")
        _apply_env(cfg)
        assert cfg.logging.level == "DEBUG"

    def test_env_web_port(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_WEB_PORT", "9999")
        _apply_env(cfg)
        assert cfg.web.port == 9999


class TestLoadConfig:
    """Tests for the full load_config function."""

    def test_load_defaults(self, tmp_path):
        # Non-existent config file → use defaults
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.training.max_new_cards == 20

    def test_load_from_file(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("[training]\nmax_new_cards = 42\n")
        config_file.chmod(0o600)
        cfg = load_config(config_file)
        assert cfg.training.max_new_cards == 42

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.toml"
        config_file.write_text("[training]\nmax_new_cards = 42\n")
        config_file.chmod(0o600)
        monkeypatch.setenv("CHESS_TRAINER_MAX_NEW_CARDS", "99")
        cfg = load_config(config_file)
        assert cfg.training.max_new_cards == 99


class TestGenerateDefaultConfig:
    """Tests for default config generation."""

    def test_generates_valid_toml(self):
        content = generate_default_config()
        data = tomllib.loads(content)
        assert "database" in data
        assert "training" in data
        assert "web" in data


# ── New helpers ───────────────────────────────────────────────────────────────


class TestSerializeToml:
    """Tests for _serialize_toml."""

    def test_roundtrip_basic_types(self):
        data = {
            "web": {"host": "0.0.0.0", "port": 9000},
            "scheduler": {"request_retention": 0.85, "learning_steps": [1, 5, 10]},
        }
        toml_str = _serialize_toml(data)
        parsed = tomllib.loads(toml_str)
        assert parsed["web"]["host"] == "0.0.0.0"
        assert parsed["web"]["port"] == 9000
        assert parsed["scheduler"]["request_retention"] == 0.85
        assert parsed["scheduler"]["learning_steps"] == [1, 5, 10]

    def test_bool_serialization(self):
        data = {"training": {"interleave_new": True}}
        toml_str = _serialize_toml(data)
        parsed = tomllib.loads(toml_str)
        assert parsed["training"]["interleave_new"] is True

    def test_bool_false(self):
        data = {"training": {"interleave_new": False}}
        toml_str = _serialize_toml(data)
        parsed = tomllib.loads(toml_str)
        assert parsed["training"]["interleave_new"] is False

    def test_none_commented_out(self):
        data = {"engine": {"path": None}}
        toml_str = _serialize_toml(data)
        assert "# path =" in toml_str
        # Should still parse without error (commented lines are ignored)
        parsed = tomllib.loads(toml_str)
        assert "path" not in parsed.get("engine", {})

    def test_empty_dict(self):
        assert _serialize_toml({}) == ""

    def test_string_with_quotes(self):
        data = {"lichess": {"api_url": 'http://example.com/path?a=1&b="2"'}}
        toml_str = _serialize_toml(data)
        parsed = tomllib.loads(toml_str)
        assert parsed["lichess"]["api_url"] == 'http://example.com/path?a=1&b="2"'


class TestGetConfigKeys:
    """Tests for get_config_keys."""

    def test_returns_dict(self):
        keys = get_config_keys()
        assert isinstance(keys, dict)

    def test_has_known_keys(self):
        keys = get_config_keys()
        assert "web.port" in keys
        assert "database.path" in keys
        assert "lichess.token" in keys
        assert "scheduler.request_retention" in keys

    def test_types_correct(self):
        keys = get_config_keys()
        assert keys["web.port"] is int
        assert keys["database.path"] is str
        assert keys["scheduler.request_retention"] is float
        assert keys["training.interleave_new"] is bool
        # Optional str | None should resolve to str
        assert keys["lichess.token"] is str

    def test_dotted_format(self):
        keys = get_config_keys()
        for k in keys:
            assert "." in k, f"Key {k!r} missing dot separator"

    def test_list_type(self):
        keys = get_config_keys()
        assert keys["scheduler.learning_steps"] is list


class TestCoerceValue:
    """Tests for coerce_value."""

    def test_int(self):
        assert coerce_value("42", int) == 42

    def test_float(self):
        assert coerce_value("0.85", float) == 0.85

    def test_bool_true_variants(self):
        for val in ("true", "True", "yes", "YES", "1"):
            assert coerce_value(val, bool) is True

    def test_bool_false_variants(self):
        for val in ("false", "False", "no", "NO", "0"):
            assert coerce_value(val, bool) is False

    def test_bool_invalid(self):
        with pytest.raises(ValueError, match="Invalid boolean"):
            coerce_value("maybe", bool)

    def test_str(self):
        assert coerce_value("hello", str) == "hello"

    def test_str_empty_returns_none(self):
        assert coerce_value("", str) is None

    def test_list_comma(self):
        assert coerce_value("1,10", list) == [1, 10]

    def test_list_bracket(self):
        assert coerce_value("[1, 10, 20]", list) == [1, 10, 20]

    def test_list_empty(self):
        assert coerce_value("[]", list) == []

    def test_int_invalid(self):
        with pytest.raises(ValueError):
            coerce_value("abc", int)


class TestValidateValue:
    """Tests for _validate_value."""

    def test_valid_port(self):
        _validate_value("web.port", 8000)  # Should not raise

    def test_invalid_port_low(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("web.port", 0)

    def test_invalid_port_high(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("web.port", 70000)

    def test_valid_retention(self):
        _validate_value("scheduler.request_retention", 0.9)

    def test_invalid_retention(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("scheduler.request_retention", 1.5)

    def test_valid_log_level(self):
        _validate_value("logging.level", "DEBUG")

    def test_invalid_log_level(self):
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value("logging.level", "TRACE")

    def test_valid_classification(self):
        _validate_value("game_analysis.min_classification", "BLUNDER")

    def test_invalid_classification(self):
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value("game_analysis.min_classification", "MINOR")

    def test_unknown_key_passes(self):
        # Keys without rules should pass silently
        _validate_value("database.path", "/any/path")


class TestGetConfigValue:
    """Tests for get_config_value."""

    def test_existing_key(self):
        cfg = AppConfig()
        assert get_config_value(cfg, "web.port") == 8000

    def test_none_value(self):
        cfg = AppConfig()
        assert get_config_value(cfg, "lichess.token") is None

    def test_unknown_section(self):
        cfg = AppConfig()
        with pytest.raises(KeyError, match="Unknown config section"):
            get_config_value(cfg, "bogus.field")

    def test_unknown_field(self):
        cfg = AppConfig()
        with pytest.raises(KeyError, match="Unknown field"):
            get_config_value(cfg, "web.bogus")

    def test_bad_format(self):
        cfg = AppConfig()
        with pytest.raises(KeyError, match="Invalid key format"):
            get_config_value(cfg, "nodotshere")


class TestSetConfigValue:
    """Tests for set_config_value."""

    def test_creates_file(self, tmp_path):
        path = tmp_path / "sub" / "config.toml"
        result = set_config_value("web.port", "9000", config_path=path)
        assert result == 9000
        assert path.is_file()
        data = tomllib.loads(path.read_text())
        assert data["web"]["port"] == 9000

    def test_updates_existing(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[web]\nport = 8000\nhost = "127.0.0.1"\n')
        set_config_value("web.port", "9000", config_path=path)
        data = tomllib.loads(path.read_text())
        assert data["web"]["port"] == 9000
        assert data["web"]["host"] == "127.0.0.1"

    def test_preserves_other_sections(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 8000\n\n[training]\nmax_new_cards = 20\n")
        set_config_value("web.port", "9000", config_path=path)
        data = tomllib.loads(path.read_text())
        assert data["web"]["port"] == 9000
        assert data["training"]["max_new_cards"] == 20

    def test_bad_key(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(KeyError, match="Unknown config key"):
            set_config_value("bogus.key", "val", config_path=path)

    def test_bad_value(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(ValueError):
            set_config_value("web.port", "abc", config_path=path)

    def test_out_of_range(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(ValueError, match="must be between"):
            set_config_value("web.port", "99999", config_path=path)

    def test_case_normalization_log_level(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("logging.level", "debug", config_path=path)
        assert result == "DEBUG"

    def test_path_expansion(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("database.path", "~/my.db", config_path=path)
        assert "~" not in str(result)
        assert str(result).endswith("my.db")


class TestResetConfigValue:
    """Tests for reset_config_value."""

    def test_reset_single_key(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[web]\nport = 9000\nhost = "127.0.0.1"\n')
        reset_config_value("web.port", config_path=path)
        data = tomllib.loads(path.read_text())
        # Port key should be removed
        assert "port" not in data.get("web", {})
        # Host should remain
        assert data["web"]["host"] == "127.0.0.1"

    def test_reset_all(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 9000\n")
        reset_config_value(config_path=path)
        content = path.read_text()
        # Should be the full default template
        assert "Chess Trainer Configuration" in content
        data = tomllib.loads(content)
        assert data["web"]["port"] == 8000

    def test_reset_bad_key(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("")
        with pytest.raises(KeyError, match="Unknown config key"):
            reset_config_value("bogus.key", config_path=path)

    def test_reset_removes_empty_section(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 9000\n")
        reset_config_value("web.port", config_path=path)
        data = tomllib.loads(path.read_text())
        assert "web" not in data

    def test_reset_nonexistent_key_in_file(self, tmp_path):
        """Resetting a key that's valid but not in the file should not error."""
        path = tmp_path / "config.toml"
        path.write_text("[training]\nmax_new_cards = 20\n")
        reset_config_value("web.port", config_path=path)
        data = tomllib.loads(path.read_text())
        assert data["training"]["max_new_cards"] == 20


class TestFilePermissions:
    """Tests for secret file permission enforcement (S1)."""

    def test_secure_file_sets_600(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 8080\n")
        path.chmod(0o644)
        _secure_file(path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_secure_file_nonexistent_no_error(self, tmp_path):
        """_secure_file silently ignores missing files."""
        _secure_file(tmp_path / "nonexistent.toml")

    def test_check_permissions_warns_on_group_readable(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[lichess]\ntoken = 'secret'\n")
        path.chmod(0o640)
        with pytest.warns(UserWarning, match="overly permissive"):
            _check_permissions(path)

    def test_check_permissions_warns_on_world_readable(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[lichess]\ntoken = 'secret'\n")
        path.chmod(0o644)
        with pytest.warns(UserWarning, match="overly permissive"):
            _check_permissions(path)

    def test_check_permissions_silent_on_600(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[lichess]\ntoken = 'secret'\n")
        path.chmod(0o600)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _check_permissions(path)

    def test_check_permissions_nonexistent_no_error(self, tmp_path):
        """_check_permissions silently ignores missing files."""
        _check_permissions(tmp_path / "nonexistent.toml")

    def test_load_config_warns_on_open_permissions(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[web]\nport = 9000\n")
        path.chmod(0o644)
        with pytest.warns(UserWarning, match="overly permissive"):
            config = load_config(path)
        assert config.web.port == 9000

    def test_set_config_value_secures_file(self, tmp_path):
        path = tmp_path / "config.toml"
        set_config_value("web.port", "9090", config_path=path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_reset_config_value_full_secures_file(self, tmp_path):
        path = tmp_path / "config.toml"
        reset_config_value(None, config_path=path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_reset_config_value_partial_secures_file(self, tmp_path):
        path = tmp_path / "config.toml"
        set_config_value("web.port", "9090", config_path=path)
        set_config_value("training.max_new_cards", "50", config_path=path)
        reset_config_value("web.port", config_path=path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_secure_file_secures_parent_directory(self, tmp_path):
        """_secure_file also sets parent directory to 0700."""
        subdir = tmp_path / "config_dir"
        subdir.mkdir(mode=0o755)
        path = subdir / "config.toml"
        path.write_text("[web]\nport = 8080\n")
        _secure_file(path)
        dir_mode = subdir.stat().st_mode & 0o777
        assert dir_mode == 0o700

    def test_set_config_value_secures_parent_directory(self, tmp_path):
        subdir = tmp_path / "config_dir"
        subdir.mkdir(mode=0o755)
        path = subdir / "config.toml"
        set_config_value("web.port", "9090", config_path=path)
        dir_mode = subdir.stat().st_mode & 0o777
        assert dir_mode == 0o700


class TestExperimentalConfigDefaults:
    """Tests for ExperimentalConfig dataclass defaults."""

    def test_defaults(self):
        cfg = ExperimentalConfig()
        assert cfg.enabled is False
        assert cfg.vision is False
        assert cfg.vision_backend == "claude"
        assert cfg.claude_api_key is None
        assert cfg.openai_api_key is None
        assert cfg.local_model_path is None

    def test_app_config_has_experimental(self):
        cfg = AppConfig()
        assert hasattr(cfg, "experimental")
        assert isinstance(cfg.experimental, ExperimentalConfig)
        assert cfg.experimental.enabled is False


class TestExperimentalApplyToml:
    """Tests for TOML overlay of [experimental] section."""

    def test_apply_experimental_all_fields(self):
        cfg = AppConfig()
        data = {
            "experimental": {
                "enabled": True,
                "vision": True,
                "vision_backend": "openai",
                "claude_api_key": "sk-ant-test",
                "openai_api_key": "sk-test",
                "local_model_path": "/path/to/model",
            }
        }
        _apply_toml(cfg, data)
        assert cfg.experimental.enabled is True
        assert cfg.experimental.vision is True
        assert cfg.experimental.vision_backend == "openai"
        assert cfg.experimental.claude_api_key == "sk-ant-test"
        assert cfg.experimental.openai_api_key == "sk-test"
        assert cfg.experimental.local_model_path == "/path/to/model"

    def test_apply_experimental_partial(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"experimental": {"enabled": True}})
        assert cfg.experimental.enabled is True
        assert cfg.experimental.vision is False  # Unchanged

    def test_apply_experimental_preserves_other_sections(self):
        cfg = AppConfig()
        _apply_toml(
            cfg,
            {
                "web": {"port": 9000},
                "experimental": {"enabled": True},
            },
        )
        assert cfg.web.port == 9000
        assert cfg.experimental.enabled is True


class TestExperimentalApplyEnv:
    """Tests for experimental env variable overrides."""

    def test_env_experimental_enabled(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_EXPERIMENTAL_ENABLED", "true")
        _apply_env(cfg)
        assert cfg.experimental.enabled is True

    def test_env_experimental_vision(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_EXPERIMENTAL_VISION", "1")
        _apply_env(cfg)
        assert cfg.experimental.vision is True

    def test_env_experimental_vision_backend(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_EXPERIMENTAL_VISION_BACKEND", "openai")
        _apply_env(cfg)
        assert cfg.experimental.vision_backend == "openai"

    def test_env_claude_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_CLAUDE_API_KEY", "sk-ant-xxx")
        _apply_env(cfg)
        assert cfg.experimental.claude_api_key == "sk-ant-xxx"

    def test_env_anthropic_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("CHESS_TRAINER_CLAUDE_API_KEY", raising=False)
        cfg = AppConfig()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback")
        _apply_env(cfg)
        assert cfg.experimental.claude_api_key == "sk-ant-fallback"

    def test_env_openai_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OPENAI_API_KEY", "sk-xxx")
        _apply_env(cfg)
        assert cfg.experimental.openai_api_key == "sk-xxx"

    def test_env_openai_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("CHESS_TRAINER_OPENAI_API_KEY", raising=False)
        cfg = AppConfig()
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")
        _apply_env(cfg)
        assert cfg.experimental.openai_api_key == "sk-fallback"


class TestIsExperimentalEnabled:
    """Tests for the is_experimental_enabled helper."""

    def test_both_false(self):
        cfg = AppConfig()
        assert is_experimental_enabled(cfg, "vision") is False

    def test_master_only(self):
        cfg = AppConfig()
        cfg.experimental.enabled = True
        assert is_experimental_enabled(cfg, "vision") is False

    def test_feature_only(self):
        cfg = AppConfig()
        cfg.experimental.vision = True
        assert is_experimental_enabled(cfg, "vision") is False

    def test_both_true(self):
        cfg = AppConfig()
        cfg.experimental.enabled = True
        cfg.experimental.vision = True
        assert is_experimental_enabled(cfg, "vision") is True

    def test_unknown_feature(self):
        cfg = AppConfig()
        cfg.experimental.enabled = True
        assert is_experimental_enabled(cfg, "nonexistent") is False


class TestExperimentalValidation:
    """Tests for experimental config validation rules."""

    def test_valid_backend_claude(self):
        _validate_value("experimental.vision_backend", "claude")

    def test_valid_backend_openai(self):
        _validate_value("experimental.vision_backend", "openai")

    def test_valid_backend_local(self):
        _validate_value("experimental.vision_backend", "local")

    def test_invalid_backend(self):
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value("experimental.vision_backend", "gemini")


class TestExperimentalSetConfigValue:
    """Tests for set/reset of experimental config keys."""

    def test_set_experimental_enabled(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("experimental.enabled", "true", config_path=path)
        assert result is True

    def test_set_vision_backend(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("experimental.vision_backend", "openai", config_path=path)
        assert result == "openai"

    def test_set_vision_backend_case_normalized(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("experimental.vision_backend", "CLAUDE", config_path=path)
        assert result == "claude"

    def test_set_vision_backend_invalid(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(ValueError, match="must be one of"):
            set_config_value("experimental.vision_backend", "gemini", config_path=path)

    def test_get_experimental_keys(self):
        keys = get_config_keys()
        assert "experimental.enabled" in keys
        assert "experimental.vision" in keys
        assert "experimental.vision_backend" in keys
        assert "experimental.claude_api_key" in keys
        assert "experimental.openai_api_key" in keys
        assert "experimental.local_model_path" in keys
        assert keys["experimental.enabled"] is bool
        assert keys["experimental.vision_backend"] is str

    def test_get_config_value_experimental(self):
        cfg = AppConfig()
        cfg.experimental.enabled = True
        assert get_config_value(cfg, "experimental.enabled") is True
        assert get_config_value(cfg, "experimental.vision_backend") == "claude"

    def test_reset_experimental_key(self, tmp_path):
        path = tmp_path / "config.toml"
        set_config_value("experimental.enabled", "true", config_path=path)
        reset_config_value("experimental.enabled", config_path=path)
        data = tomllib.loads(path.read_text())
        assert "enabled" not in data.get("experimental", {})


class TestExperimentalDefaultConfig:
    """Tests for experimental section in generated default config."""

    def test_default_config_has_experimental_commented(self):
        content = generate_default_config()
        assert "# [experimental]" in content
        assert "# enabled = false" in content
        assert '# vision_backend = "claude"' in content


# ── OwnGameEvalConfig tests ──────────────────────────────────────────────────


class TestOwnGameEvalConfigDefaults:
    """Tests for OwnGameEvalConfig dataclass defaults."""

    def test_defaults(self):
        cfg = OwnGameEvalConfig()
        assert cfg.cp_tolerance == 50
        assert cfg.multipv_count == 3
        assert cfg.evaluate_depth == 1
        assert cfg.show_game_context is True

    def test_app_config_has_own_game_eval(self):
        cfg = AppConfig()
        assert hasattr(cfg, "own_game_eval")
        assert isinstance(cfg.own_game_eval, OwnGameEvalConfig)
        assert cfg.own_game_eval.cp_tolerance == 50


class TestOwnGameEvalApplyToml:
    """Tests for TOML overlay of [own_game_eval] section."""

    def test_apply_all_fields(self):
        cfg = AppConfig()
        data = {
            "own_game_eval": {
                "cp_tolerance": 75,
                "multipv_count": 5,
                "evaluate_depth": 3,
                "show_game_context": False,
            }
        }
        _apply_toml(cfg, data)
        assert cfg.own_game_eval.cp_tolerance == 75
        assert cfg.own_game_eval.multipv_count == 5
        assert cfg.own_game_eval.evaluate_depth == 3
        assert cfg.own_game_eval.show_game_context is False

    def test_apply_partial(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"own_game_eval": {"cp_tolerance": 100}})
        assert cfg.own_game_eval.cp_tolerance == 100
        assert cfg.own_game_eval.multipv_count == 3  # Unchanged

    def test_preserves_other_sections(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"web": {"port": 9000}, "own_game_eval": {"cp_tolerance": 30}})
        assert cfg.web.port == 9000
        assert cfg.own_game_eval.cp_tolerance == 30


class TestOwnGameEvalApplyEnv:
    """Tests for own_game_eval env variable overrides."""

    def test_env_cp_tolerance(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OWN_GAME_CP_TOLERANCE", "100")
        _apply_env(cfg)
        assert cfg.own_game_eval.cp_tolerance == 100

    def test_env_multipv(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OWN_GAME_MULTIPV", "5")
        _apply_env(cfg)
        assert cfg.own_game_eval.multipv_count == 5

    def test_env_eval_depth(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OWN_GAME_EVAL_DEPTH", "2")
        _apply_env(cfg)
        assert cfg.own_game_eval.evaluate_depth == 2

    def test_env_show_context(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OWN_GAME_SHOW_CONTEXT", "false")
        _apply_env(cfg)
        assert cfg.own_game_eval.show_game_context is False


class TestOwnGameEvalValidation:
    """Tests for own_game_eval validation rules."""

    def test_valid_cp_tolerance(self):
        _validate_value("own_game_eval.cp_tolerance", 50)

    def test_invalid_cp_tolerance_high(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("own_game_eval.cp_tolerance", 600)

    def test_valid_multipv_count(self):
        _validate_value("own_game_eval.multipv_count", 3)

    def test_invalid_multipv_count(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("own_game_eval.multipv_count", 0)

    def test_valid_evaluate_depth(self):
        _validate_value("own_game_eval.evaluate_depth", 1)

    def test_invalid_evaluate_depth(self):
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("own_game_eval.evaluate_depth", 0)


class TestOwnGameEvalSetConfig:
    """Tests for set/get of own_game_eval config keys."""

    def test_get_config_keys_includes_own_game_eval(self):
        keys = get_config_keys()
        assert "own_game_eval.cp_tolerance" in keys
        assert "own_game_eval.multipv_count" in keys
        assert "own_game_eval.evaluate_depth" in keys
        assert "own_game_eval.show_game_context" in keys
        assert keys["own_game_eval.cp_tolerance"] is int
        assert keys["own_game_eval.show_game_context"] is bool

    def test_get_config_value(self):
        cfg = AppConfig()
        assert get_config_value(cfg, "own_game_eval.cp_tolerance") == 50
        assert get_config_value(cfg, "own_game_eval.show_game_context") is True

    def test_set_config_value(self, tmp_path):
        path = tmp_path / "config.toml"
        result = set_config_value("own_game_eval.cp_tolerance", "75", config_path=path)
        assert result == 75

    def test_set_config_out_of_range(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(ValueError, match="must be between"):
            set_config_value("own_game_eval.cp_tolerance", "999", config_path=path)


class TestOwnGameEvalDefaultConfig:
    """Tests for own_game_eval section in generated default config."""

    def test_default_config_has_own_game_eval_commented(self):
        content = generate_default_config()
        assert "# [own_game_eval]" in content
        assert "# cp_tolerance = 50" in content
        assert "# evaluate_depth = 1" in content
        assert "# show_game_context = true" in content


class TestTrainingDefaultMode:
    """Tests for training.default_mode config field."""

    def test_default_mode_default_value(self):
        cfg = AppConfig()
        assert cfg.training.default_mode == "study"

    def test_apply_toml_default_mode(self):
        cfg = AppConfig()
        _apply_toml(cfg, {"training": {"default_mode": "test"}})
        assert cfg.training.default_mode == "test"

    def test_apply_env_training_mode(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_TRAINING_MODE", "TEST")
        _apply_env(cfg)
        assert cfg.training.default_mode == "test"

    def test_validation_valid_modes(self):
        _validate_value("training.default_mode", "study")
        _validate_value("training.default_mode", "test")

    def test_validation_invalid_mode(self):
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value("training.default_mode", "invalid")

    def test_default_config_has_mode_commented(self):
        content = generate_default_config()
        assert "default_mode" in content
