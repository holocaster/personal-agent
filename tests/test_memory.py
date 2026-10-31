import re

import pytest

from personal_agent import memory


def test_resolve_path_returns_default_when_env_var_unset(monkeypatch):
    monkeypatch.delenv(memory.MEMORY_PATH_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", "/home/example")

    assert memory.resolve_path() == "/home/example/.personal_agent/memory.jsonl"


def test_resolve_path_returns_default_when_env_var_empty(monkeypatch):
    monkeypatch.setenv(memory.MEMORY_PATH_ENV_VAR, "")
    monkeypatch.setenv("HOME", "/home/example")

    assert memory.resolve_path() == "/home/example/.personal_agent/memory.jsonl"


def test_resolve_path_uses_the_env_var_as_the_exact_file(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "notes.jsonl"
    monkeypatch.setenv(memory.MEMORY_PATH_ENV_VAR, str(target))

    assert memory.resolve_path() == str(target)


def test_resolve_path_expands_a_tilde_in_the_env_var(monkeypatch):
    monkeypatch.setenv("HOME", "/home/example")
    monkeypatch.setenv(memory.MEMORY_PATH_ENV_VAR, "~/elsewhere/memory.jsonl")

    assert memory.resolve_path() == "/home/example/elsewhere/memory.jsonl"


def test_load_returns_empty_list_for_a_missing_file(tmp_path):
    path = str(tmp_path / "does-not-exist.jsonl")

    assert memory.load(path) == []


def test_load_ignores_blank_lines_and_keeps_order(tmp_path):
    path = tmp_path / "memory.jsonl"
    path.write_text(
        '{"text": "first", "added": "2026-09-22T00:00:00.000Z"}\n'
        "\n"
        '{"text": "second", "added": "2026-09-22T00:00:01.000Z"}\n'
    )

    notes = memory.load(str(path))

    assert notes == [
        {"text": "first", "added": "2026-09-22T00:00:00.000Z"},
        {"text": "second", "added": "2026-09-22T00:00:01.000Z"},
    ]


@pytest.mark.parametrize(
    "bad_line",
    [
        "not json",
        "[]",
        '{"text": "missing added"}',
        '{"added": "2026-09-22T00:00:00.000Z"}',
        '{"text": 1, "added": "2026-09-22T00:00:00.000Z"}',
        '{"text": "ok", "added": 1}',
    ],
)
def test_load_raises_for_a_malformed_line_naming_the_file(tmp_path, bad_line):
    path = tmp_path / "memory.jsonl"
    path.write_text(bad_line + "\n")

    with pytest.raises(ValueError) as exc_info:
        memory.load(str(path))

    assert str(path) in str(exc_info.value)


def test_load_raises_for_a_line_with_invalid_utf8_naming_the_file(tmp_path):
    path = tmp_path / "memory.jsonl"
    path.write_bytes(b"\xff\xfe\n")

    with pytest.raises(ValueError) as exc_info:
        memory.load(str(path))

    assert str(path) in str(exc_info.value)


def test_remember_appends_one_line_with_text_and_added_timestamp(tmp_path):
    path = tmp_path / "memory.jsonl"

    note = memory.remember("a fact", str(path))

    assert note["text"] == "a fact"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", note["added"])
    assert memory.load(str(path)) == [note]


def test_remember_creates_the_parent_directory_when_needed(tmp_path):
    path = tmp_path / "nested" / "dir" / "memory.jsonl"

    memory.remember("a fact", str(path))

    assert path.is_file()


def test_remember_appends_without_disturbing_earlier_notes(tmp_path):
    path = tmp_path / "memory.jsonl"
    memory.remember("first", str(path))

    memory.remember("second", str(path))

    assert [note["text"] for note in memory.load(str(path))] == ["first", "second"]


def test_forget_removes_the_note_at_the_1_based_index_and_keeps_the_rest(tmp_path):
    path = tmp_path / "memory.jsonl"
    memory.remember("first", str(path))
    memory.remember("second", str(path))
    memory.remember("third", str(path))

    notes = memory.load(str(path))

    removed = memory.forget(2, notes, str(path))

    assert removed["text"] == "second"
    remaining = memory.load(str(path))
    assert [note["text"] for note in remaining] == ["first", "third"]
    assert remaining[0]["added"] and remaining[1]["added"]


def test_forget_the_only_note_leaves_an_empty_file(tmp_path):
    path = tmp_path / "memory.jsonl"
    memory.remember("only", str(path))
    notes = memory.load(str(path))

    memory.forget(1, notes, str(path))

    assert memory.load(str(path)) == []


@pytest.mark.parametrize("index", [0, -1, 2])
def test_forget_raises_index_error_out_of_range(tmp_path, index):
    path = tmp_path / "memory.jsonl"
    memory.remember("only", str(path))
    notes = memory.load(str(path))

    with pytest.raises(IndexError):
        memory.forget(index, notes, str(path))

    assert [note["text"] for note in memory.load(str(path))] == ["only"]


def test_forget_acts_on_the_given_notes_not_a_fresh_read_of_the_file(tmp_path):
    path = tmp_path / "memory.jsonl"
    memory.remember("A", str(path))
    memory.remember("B", str(path))
    notes = memory.load(str(path))
    path.write_text('{"text": "B", "added": "2026-09-22T00:00:01.000Z"}\n')

    removed = memory.forget(1, notes, str(path))

    assert removed["text"] == "A"
    assert [note["text"] for note in memory.load(str(path))] == ["B"]
