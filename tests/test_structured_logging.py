"""Tests for E12 — Structured logging (JSONFormatter, file logging, config)."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

# ── JSONFormatter ──────────────────────────────────────────────────────────────


class TestJSONFormatter:
    """Tests for the JSONFormatter class."""

    def test_basic_output_is_valid_json(self):
        from src import JSONFormatter

        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        line = fmt.format(record)
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "hello world"
        assert "timestamp" in data
        assert "exception" not in data

    def test_exception_included(self):
        from src import JSONFormatter

        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.exc",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        line = fmt.format(record)
        data = json.loads(line)
        assert "exception" in data
        assert "ValueError: boom" in data["exception"]

    def test_message_with_args(self):
        from src import JSONFormatter

        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="count=%d",
            args=(42,),
            exc_info=None,
        )
        line = fmt.format(record)
        data = json.loads(line)
        assert data["message"] == "count=42"

    def test_no_exception_when_exc_info_is_none_tuple(self):
        from src import JSONFormatter

        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="ok",
            args=(),
            exc_info=(None, None, None),
        )
        line = fmt.format(record)
        data = json.loads(line)
        assert "exception" not in data


# ── configure_logging ──────────────────────────────────────────────────────────


class TestConfigureLogging:
    """Tests for the expanded configure_logging function."""

    def test_sets_level(self):
        from src import _pkg_logger, configure_logging

        configure_logging(level="DEBUG")
        assert _pkg_logger.level == logging.DEBUG
        configure_logging(level="INFO")  # restore

    def test_file_handler_added_with_text(self, tmp_path):
        from src import _pkg_logger, configure_logging

        log_file = str(tmp_path / "test.log")
        configure_logging(level="INFO", file=log_file, format="text")
        try:
            file_handlers = [h for h in _pkg_logger.handlers if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) == 1
            handler = file_handlers[0]
            assert handler.maxBytes == 10 * 1024 * 1024
            assert handler.backupCount == 3
            # Text formatter check
            assert not isinstance(handler.formatter, type(None))
        finally:
            configure_logging(level="INFO")  # removes file handlers

    def test_file_handler_added_with_json(self, tmp_path):
        from src import JSONFormatter, _pkg_logger, configure_logging

        log_file = str(tmp_path / "test.json.log")
        configure_logging(level="INFO", file=log_file, format="json")
        try:
            file_handlers = [h for h in _pkg_logger.handlers if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) == 1
            assert isinstance(file_handlers[0].formatter, JSONFormatter)
        finally:
            configure_logging(level="INFO")

    def test_rotation_params(self, tmp_path):
        from src import _pkg_logger, configure_logging

        log_file = str(tmp_path / "rot.log")
        configure_logging(level="INFO", file=log_file, max_size_mb=5, backup_count=7)
        try:
            file_handlers = [h for h in _pkg_logger.handlers if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) == 1
            assert file_handlers[0].maxBytes == 5 * 1024 * 1024
            assert file_handlers[0].backupCount == 7
        finally:
            configure_logging(level="INFO")

    def test_no_file_handler_without_file(self):
        from src import _pkg_logger, configure_logging

        configure_logging(level="INFO")
        file_handlers = [h for h in _pkg_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 0

    def test_reconfigure_removes_old_file_handler(self, tmp_path):
        from src import _pkg_logger, configure_logging

        log_file1 = str(tmp_path / "a.log")
        log_file2 = str(tmp_path / "b.log")
        configure_logging(level="INFO", file=log_file1)
        configure_logging(level="INFO", file=log_file2)
        try:
            file_handlers = [h for h in _pkg_logger.handlers if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) == 1
        finally:
            configure_logging(level="INFO")

    def test_writes_to_file(self, tmp_path):
        from src import _pkg_logger, configure_logging

        log_file = tmp_path / "write.log"
        configure_logging(level="INFO", file=str(log_file), format="text")
        try:
            _pkg_logger.info("test message")
            content = log_file.read_text()
            assert "test message" in content
        finally:
            configure_logging(level="INFO")

    def test_writes_json_to_file(self, tmp_path):
        from src import _pkg_logger, configure_logging

        log_file = tmp_path / "write.json.log"
        configure_logging(level="INFO", file=str(log_file), format="json")
        try:
            _pkg_logger.info("json test")
            content = log_file.read_text().strip()
            data = json.loads(content)
            assert data["message"] == "json test"
            assert data["level"] == "INFO"
        finally:
            configure_logging(level="INFO")

    def test_creates_parent_dirs(self, tmp_path):
        from src import configure_logging

        log_file = str(tmp_path / "deep" / "nested" / "test.log")
        configure_logging(level="INFO", file=log_file)
        try:
            assert Path(log_file).parent.is_dir()
        finally:
            configure_logging(level="INFO")


# ── get_logger ─────────────────────────────────────────────────────────────────


class TestGetLogger:
    """Tests for the get_logger guard against duplicate handlers."""

    def test_no_duplicate_rich_handlers(self):
        from rich.logging import RichHandler

        from src import get_logger

        logger = get_logger("test.dup")
        logger2 = get_logger("test.dup")
        assert logger is logger2
        rich_count = sum(1 for h in logger.handlers if isinstance(h, RichHandler))
        assert rich_count == 1


# ── Config ─────────────────────────────────────────────────────────────────────


class TestLoggingConfig:
    """Tests for LoggingConfig fields, TOML parsing, env, and validation."""

    def test_defaults(self):
        from src.config import LoggingConfig

        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.file is None
        assert cfg.format == "text"
        assert cfg.max_size_mb == 10
        assert cfg.backup_count == 3

    def test_toml_parsing(self, tmp_path):
        from src.config import load_config

        toml = tmp_path / "config.toml"
        toml.write_text("""\
[logging]
level = "DEBUG"
file = "/tmp/test.log"
format = "json"
max_size_mb = 50
backup_count = 10
""")
        cfg = load_config(toml)
        assert cfg.logging.level == "DEBUG"
        assert cfg.logging.file == "/tmp/test.log"
        assert cfg.logging.format == "json"
        assert cfg.logging.max_size_mb == 50
        assert cfg.logging.backup_count == 10

    def test_toml_file_path_expansion(self, tmp_path):
        from src.config import load_config

        toml = tmp_path / "config.toml"
        toml.write_text('[logging]\nfile = "~/logs/chess.log"\n')
        cfg = load_config(toml)
        assert "~" not in cfg.logging.file
        assert cfg.logging.file.endswith("logs/chess.log")

    def test_env_overrides(self, monkeypatch, tmp_path):
        from src.config import load_config

        toml = tmp_path / "empty.toml"
        toml.write_text("")
        monkeypatch.setenv("CHESS_TRAINER_LOG_FILE", "/var/log/ct.log")
        monkeypatch.setenv("CHESS_TRAINER_LOG_FORMAT", "JSON")
        cfg = load_config(toml)
        assert cfg.logging.file == "/var/log/ct.log"
        assert cfg.logging.format == "json"

    def test_validation_format_enum(self):
        from src.config import _validate_value

        _validate_value("logging.format", "json")
        _validate_value("logging.format", "text")
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value("logging.format", "xml")

    def test_validation_max_size_range(self):
        from src.config import _validate_value

        _validate_value("logging.max_size_mb", 1)
        _validate_value("logging.max_size_mb", 1000)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("logging.max_size_mb", 0)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("logging.max_size_mb", 1001)

    def test_validation_backup_count_range(self):
        from src.config import _validate_value

        _validate_value("logging.backup_count", 0)
        _validate_value("logging.backup_count", 100)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("logging.backup_count", -1)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("logging.backup_count", 101)

    def test_generate_default_config_includes_logging_fields(self):
        from src.config import generate_default_config

        cfg = generate_default_config()
        assert "format" in cfg
        assert "max_size_mb" in cfg
        assert "backup_count" in cfg
