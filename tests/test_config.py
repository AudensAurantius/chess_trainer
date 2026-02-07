"""Tests for the TOML configuration system."""

from src.config import (
    AppConfig,
    _apply_env,
    _apply_toml,
    generate_default_config,
    load_config,
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
        cfg = load_config(config_file)
        assert cfg.training.max_new_cards == 42

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.toml"
        config_file.write_text("[training]\nmax_new_cards = 42\n")
        monkeypatch.setenv("CHESS_TRAINER_MAX_NEW_CARDS", "99")
        cfg = load_config(config_file)
        assert cfg.training.max_new_cards == 99


class TestGenerateDefaultConfig:
    """Tests for default config generation."""

    def test_generates_valid_toml(self):
        import tomllib

        content = generate_default_config()
        data = tomllib.loads(content)
        assert "database" in data
        assert "training" in data
        assert "web" in data
