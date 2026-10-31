import os

import pytest

from personal_agent.dotenv import load_dotenv


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("DOTENV_A", "DOTENV_B", "DOTENV_C", "DOTENV_ALREADY_SET"):
        monkeypatch.delenv(key, raising=False)


def test_missing_file_is_a_no_op(tmp_path):
    load_dotenv(str(tmp_path / "does-not-exist.env"))


def test_sets_vars_from_key_value_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DOTENV_A=one\nDOTENV_B=two\n")

    load_dotenv(str(env_file))

    assert os.environ["DOTENV_A"] == "one"
    assert os.environ["DOTENV_B"] == "two"


def test_skips_blank_lines_and_comments(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("\n# a comment\nDOTENV_A=one\n")

    load_dotenv(str(env_file))

    assert os.environ["DOTENV_A"] == "one"


def test_strips_matching_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('DOTENV_A="quoted value"\nDOTENV_B=\'single quoted\'\n')

    load_dotenv(str(env_file))

    assert os.environ["DOTENV_A"] == "quoted value"
    assert os.environ["DOTENV_B"] == "single quoted"


def test_does_not_override_an_already_set_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("DOTENV_ALREADY_SET", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("DOTENV_ALREADY_SET=from-file\n")

    load_dotenv(str(env_file))

    assert os.environ["DOTENV_ALREADY_SET"] == "from-shell"
