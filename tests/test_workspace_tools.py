import json
from pathlib import Path

import pytest

from personal_agent import call_log, file_recovery
from personal_agent.routing import runtime_config
from personal_agent.tools import registry as tools, workspace
from personal_agent.providers.contract import ToolCall


def test_list_files_returns_workspace_relative_files_in_order(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    workspace.configure_workspace(tmp_path)

    result = tools.execute_batch([ToolCall(id="1", name="list_files", arguments={})])[0]

    assert result.is_error is False
    assert result.content == {"files": ["a.txt", "nested/b.txt"], "truncated": False}
    assert _execute("list_files", {"path": "nested"}).content == {"files": ["nested/b.txt"], "truncated": False}


def _execute(name, arguments):
    return tools.execute_batch([ToolCall(id="1", name=name, arguments=arguments)])[0]


def test_list_files_stops_walking_after_the_first_excess_match(tmp_path, monkeypatch):
    for index in range(101):
        (tmp_path / f"a{index:03d}.txt").write_text("x")
    (tmp_path / "z_later").mkdir()
    (tmp_path / "z_later" / "unused.txt").write_text("x")
    workspace.configure_workspace(tmp_path)
    visited = []
    original_iterdir = Path.iterdir

    def counted_iterdir(path):
        visited.append(path.relative_to(tmp_path).as_posix())
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)

    result = _execute("list_files", {})

    assert result.content == {
        "files": [f"a{index:03d}.txt" for index in range(100)],
        "truncated": True,
    }
    assert visited == ["."]


@pytest.mark.parametrize("matching_count", [100, 101])
def test_list_files_filters_before_its_limit_and_checks_for_an_excess_match(tmp_path, monkeypatch, matching_count):
    root = tmp_path / "src"
    root.mkdir()
    for index in range(150):
        (root / f"a{index:03d}.txt").write_text("x")
    (root / "b_matches").mkdir()
    for index in range(matching_count):
        (root / "b_matches" / f"m{index:03d}.py").write_text("x")
    (root / "z_later").mkdir()
    (root / "z_later" / "unused.txt").write_text("x")
    workspace.configure_workspace(tmp_path)
    visited = []
    original_iterdir = Path.iterdir

    def counted_iterdir(path):
        visited.append(path.relative_to(root).as_posix())
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)

    result = _execute("list_files", {"path": "src", "pattern": "**/*.py"})

    assert result.content == {
        "files": [f"src/b_matches/m{index:03d}.py" for index in range(100)],
        "truncated": matching_count > 100,
    }
    assert visited == ([".", "b_matches"] if matching_count > 100 else [".", "b_matches", "z_later"])


@pytest.mark.parametrize("search_root", [".", "src"])
def test_workspace_walk_preserves_posix_lexical_path_and_search_line_order(tmp_path, search_root):
    root = tmp_path / search_root
    root.mkdir(exist_ok=True)
    ordered_paths = ["a-early.txt", "a.txt", "a/b.txt", "a/b/file.txt", "a/file.txt", "a0.txt", "a_last.txt"]
    for relative_path in reversed(ordered_paths):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("needle first\nno match\nNEEDLE last\n")
    workspace.configure_workspace(tmp_path)
    expected_paths = [path if search_root == "." else f"src/{path}" for path in ordered_paths]

    listing = _execute("list_files", {"path": search_root})
    search = _execute("search_text", {"text": "needle", "path": search_root})

    assert listing.content == {"files": expected_paths, "truncated": False}
    assert search.content == {
        "matches": [
            {"path": path, "line": line_number, "excerpt": excerpt}
            for path in expected_paths
            for line_number, excerpt in [(1, "needle first"), (3, "NEEDLE last")]
        ],
        "truncated": False,
    }


@pytest.mark.parametrize(
    "max_read_bytes, line_count, expected_count, truncated",
    [(None, 101, 100, True), ("60", 2, 1, True), (None, 100, 100, False)],
)
def test_search_text_stops_walking_when_its_filtered_result_or_output_limit_is_established(
    tmp_path, monkeypatch, max_read_bytes, line_count, expected_count, truncated
):
    root = tmp_path / "src"
    (root / "a_skipped").mkdir(parents=True)
    (root / "a_skipped" / "ignored.txt").write_text("needle\n" * 150)
    (root / "b_hits.py").write_text("needle\n" * line_count)
    (root / "z_later").mkdir()
    (root / "z_later" / "unused.py").write_text("no match")
    workspace.configure_workspace(tmp_path, max_read_bytes)
    visited = []
    read = []
    original_iterdir = Path.iterdir
    original_read_bytes = Path.read_bytes

    def counted_iterdir(path):
        visited.append(path.relative_to(root).as_posix())
        return original_iterdir(path)

    def counted_read_bytes(path):
        read.append(path.relative_to(root).as_posix())
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)
    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)

    result = _execute("search_text", {"text": "needle", "path": "src", "glob": "**/*.py"})

    assert result.content == {
        "matches": [
            {"path": "src/b_hits.py", "line": line_number, "excerpt": "needle"}
            for line_number in range(1, expected_count + 1)
        ],
        "truncated": truncated,
    }
    assert visited == ([".", "a_skipped"] if truncated else [".", "a_skipped", "z_later"])
    assert read == (["b_hits.py"] if truncated else ["b_hits.py", "z_later/unused.py"])


def test_workspace_configuration_defaults_and_rejects_invalid_limits(tmp_path):
    configured = workspace.configure_workspace(tmp_path)

    assert configured.root == tmp_path.resolve()
    assert configured.max_read_bytes == 32 * 1024
    with pytest.raises(ValueError, match="PA_MAX_READ_BYTES"):
        workspace.configure_workspace(tmp_path, "0")
    with pytest.raises(ValueError, match="PA_MAX_READ_BYTES"):
        workspace.configure_workspace(tmp_path, "1.5")
    with pytest.raises(ValueError, match="Workspace Root"):
        workspace.configure_workspace(tmp_path / "missing")


def test_workspace_tool_schemas_are_advertised():
    definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert set(("list_files", "read_file", "search_text")) <= definitions.keys()
    assert definitions["read_file"]["required"] == ["path"]
    assert definitions["read_file"]["properties"]["offset"] == {"type": "integer", "minimum": 1, "default": 1}
    assert definitions["read_file"]["properties"]["limit"] == {"type": "integer", "minimum": 1, "default": 500}
    assert definitions["search_text"]["required"] == ["text"]
    assert definitions["search_text"]["properties"]["text"]["minLength"] == 1


def test_list_files_includes_hidden_and_ignored_files_but_excludes_secrets_and_deep_files(tmp_path):
    (tmp_path / ".hidden").write_text("hidden")
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("ignored")
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "secret.pem").write_text("secret")
    (tmp_path / "secret.key").write_text("secret")
    deep = tmp_path
    for index in range(9):
        deep /= f"d{index}"
        deep.mkdir()
    (deep / "too-deep.txt").write_text("deep")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {})

    assert result.content["files"] == [".gitignore", ".hidden", "ignored.txt"]
    assert result.content["truncated"] is False


def test_list_files_bounds_results_and_skips_unsafe_symlinks(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / "safe.txt").write_text("safe")
    (tmp_path / "file-link.txt").symlink_to(tmp_path / "safe.txt")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir-link").symlink_to(tmp_path / "dir", target_is_directory=True)
    (tmp_path / "outside-link.txt").symlink_to(outside)
    for index in range(101):
        (tmp_path / f"file-{index}.txt").write_text("x")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {})

    assert result.is_error is False
    assert len(result.content["files"]) == 100
    assert result.content["truncated"] is True
    assert "dir-link" not in result.content["files"]
    assert "outside-link.txt" not in result.content["files"]
    assert _execute("read_file", {"path": "file-link.txt"}).content == {
        "content": "1\tsafe",
        "has_more": False,
        "next_offset": None,
    }


def test_read_file_rejects_binary_and_unsafe_targets(tmp_path):
    (tmp_path / "text.txt").write_text("complete text")
    (tmp_path / "binary.bin").write_bytes(b"x\0")
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "secret-alias.txt").symlink_to(tmp_path / ".env")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / "outside-link.txt").symlink_to(outside)
    workspace.configure_workspace(tmp_path)

    assert "binary" in _execute("read_file", {"path": "binary.bin"}).content["error"]
    assert "excluded" in _execute("read_file", {"path": ".env"}).content["error"]
    assert "excluded" in _execute("read_file", {"path": "secret-alias.txt"}).content["error"]
    assert "relative" in _execute("read_file", {"path": str(tmp_path / "text.txt")}).content["error"]
    assert "traversal" in _execute("read_file", {"path": "../text.txt"}).content["error"]
    assert "outside" in _execute("read_file", {"path": "outside-link.txt"}).content["error"]

    result = _execute("read_file", {"path": "text.txt"})
    assert result.content == {"content": "1\tcomplete text", "has_more": False, "next_offset": None}


def test_safe_intermediate_directory_alias_preserves_read_list_search_and_glob_paths(tmp_path):
    (tmp_path / "real/nested/deep").mkdir(parents=True)
    (tmp_path / "real/nested/a.txt").write_text("needle first")
    (tmp_path / "real/nested/deep/b.txt").write_text("needle last")
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    workspace.configure_workspace(tmp_path)

    assert _execute("read_file", {"path": "alias/nested/a.txt"}).content == {
        "content": "1\tneedle first", "has_more": False, "next_offset": None,
    }
    assert _execute("list_files", {"path": "alias/nested", "pattern": "**/*.txt"}).content == {
        "files": ["alias/nested/a.txt", "alias/nested/deep/b.txt"], "truncated": False,
    }
    assert _execute("search_text", {"path": "alias/nested", "text": "needle", "glob": "deep/*.txt"}).content == {
        "matches": [{"path": "alias/nested/deep/b.txt", "line": 1, "excerpt": "needle last"}], "truncated": False,
    }


def test_read_file_offset_and_limit_produce_a_numbered_window_with_has_more_and_next_offset(tmp_path):
    (tmp_path / "lines.txt").write_text("one\ntwo\nthree\nfour\nfive\n")
    workspace.configure_workspace(tmp_path)

    whole = _execute("read_file", {"path": "lines.txt"})
    assert whole.content == {
        "content": "1\tone\n2\ttwo\n3\tthree\n4\tfour\n5\tfive\n",
        "has_more": False,
        "next_offset": None,
    }

    windowed = _execute("read_file", {"path": "lines.txt", "offset": 2, "limit": 2})
    assert windowed.content == {"content": "2\ttwo\n3\tthree\n", "has_more": True, "next_offset": 4}

    tail = _execute("read_file", {"path": "lines.txt", "offset": 4, "limit": 2})
    assert tail.content == {"content": "4\tfour\n5\tfive\n", "has_more": False, "next_offset": None}


def test_read_file_cuts_the_window_at_the_last_whole_line_that_fits_the_cap(tmp_path):
    (tmp_path / "lines.txt").write_text("aa\nbb\ncc\n")
    workspace.configure_workspace(tmp_path, "10")

    result = _execute("read_file", {"path": "lines.txt"})

    assert result.content == {"content": "1\taa\n2\tbb\n", "has_more": True, "next_offset": 3}
    follow_up = _execute("read_file", {"path": "lines.txt", "offset": 3})
    assert follow_up.content == {"content": "3\tcc\n", "has_more": False, "next_offset": None}


def test_read_file_first_line_alone_over_the_cap_is_truncated_with_the_marker(tmp_path):
    (tmp_path / "big-line.txt").write_text("x" * 100 + "\nsecond\n")
    workspace.configure_workspace(tmp_path, "30")

    result = _execute("read_file", {"path": "big-line.txt"})

    assert result.content == {
        "content": "1\t" + "x" * 14 + "[...truncated]",
        "has_more": True,
        "next_offset": 2,
    }
    follow_up = _execute("read_file", {"path": "big-line.txt", "offset": 2})
    assert follow_up.content == {"content": "2\tsecond\n", "has_more": False, "next_offset": None}


def test_read_file_r7_truncation_cuts_on_a_utf8_character_boundary(tmp_path):
    line = "a" * 13 + "é" * 10
    (tmp_path / "utf8-line.txt").write_text(line + "\n")
    workspace.configure_workspace(tmp_path, "30")

    result = _execute("read_file", {"path": "utf8-line.txt"})

    assert result.content == {
        "content": "1\t" + "a" * 13 + "[...truncated]",
        "has_more": False,
        "next_offset": None,
    }


def test_read_file_binary_check_is_scoped_to_bytes_in_the_returned_window(tmp_path):
    (tmp_path / "mixed.bin").write_bytes(b"ok line\nbinary:\x00after\n")
    workspace.configure_workspace(tmp_path)

    result = _execute("read_file", {"path": "mixed.bin", "offset": 1, "limit": 1})

    assert result.content == {"content": "1\tok line\n", "has_more": True, "next_offset": 2}
    error_result = _execute("read_file", {"path": "mixed.bin", "offset": 2})
    assert "binary" in error_result.content["error"]


def test_read_file_offset_past_end_is_an_error_naming_the_line_count(tmp_path):
    (tmp_path / "one-line.txt").write_text("only line\n")
    (tmp_path / "empty.txt").write_bytes(b"")
    workspace.configure_workspace(tmp_path)

    single_line_error = _execute("read_file", {"path": "one-line.txt", "offset": 2})
    assert single_line_error.content["error"] == "offset 2 is past end of file (1 line)"

    far_past_end = _execute("read_file", {"path": "one-line.txt", "offset": 5})
    assert far_past_end.content["error"] == "offset 5 is past end of file (1 line)"

    empty_error = _execute("read_file", {"path": "empty.txt", "offset": 2})
    assert empty_error.content["error"] == "offset 2 is past end of file (0 lines)"

    empty_success = _execute("read_file", {"path": "empty.txt"})
    assert empty_success.content == {"content": "", "has_more": False, "next_offset": None}


def test_read_file_streams_a_multi_mb_file_and_a_multi_mb_single_line_at_offset_one(tmp_path):
    big_file = tmp_path / "big.txt"
    with big_file.open("w") as handle:
        for _ in range(200_000):
            handle.write("line of text\n")
    (tmp_path / "single-line.txt").write_text("y" * (3 * 1024 * 1024))
    workspace.configure_workspace(tmp_path)

    result = _execute("read_file", {"path": "big.txt"})
    assert result.content["has_more"] is True
    assert result.content["next_offset"] is not None
    assert len(result.content["content"].encode("utf-8")) <= 32 * 1024

    single_result = _execute("read_file", {"path": "single-line.txt"})
    assert single_result.content["content"].endswith("[...truncated]")
    assert single_result.content["has_more"] is False
    assert single_result.content["next_offset"] is None


def test_read_file_and_edit_descriptions_carry_the_read_window_warning():
    definitions = {definition.name: definition for definition in tools.TOOL_DEFS}

    read_description = definitions["read_file"].description
    assert "offset" in read_description
    assert "limit" in read_description
    assert "next_offset" in read_description
    assert "has_more" in read_description
    assert "not part of the file" in read_description

    edit_description = definitions["edit"].description
    assert "old_string" in edit_description
    assert "line-number prefix" in edit_description
    assert "read_file" in edit_description


def test_search_text_is_literal_case_insensitive_bounded_and_skips_binary_directory_files(tmp_path):
    (tmp_path / "a.txt").write_text("first Needle\nnope\nneedle again\n")
    (tmp_path / "b.txt").write_text("NEEDLE\n")
    (tmp_path / "literal.txt").write_text("a.b\nabc\n")
    (tmp_path / "binary.bin").write_bytes(b"needle\0")
    (tmp_path / ".env").write_text("needle")
    for index in range(101):
        (tmp_path / f"many-{index}.txt").write_text("needle")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "Needle", "path": "a.txt"})

    assert result.content == {
        "matches": [
            {"path": "a.txt", "line": 1, "excerpt": "first Needle"},
            {"path": "a.txt", "line": 3, "excerpt": "needle again"},
        ],
        "truncated": False,
    }
    assert _execute("search_text", {"text": ".", "path": "literal.txt"}).content["matches"] == [
        {"path": "literal.txt", "line": 1, "excerpt": "a.b"}
    ]
    directory_result = _execute("search_text", {"text": "needle"})
    assert directory_result.is_error is False
    assert len(directory_result.content["matches"]) == 100
    assert directory_result.content["truncated"] is True
    assert all(match["path"] != ".env" for match in directory_result.content["matches"])
    assert "binary" in _execute("search_text", {"text": "needle", "path": "binary.bin"}).content["error"]
    assert "excluded" in _execute("search_text", {"text": "needle", "path": ".env"}).content["error"]


def test_search_text_excerpt_excludes_the_line_terminator_and_a_preceding_cr(tmp_path):
    (tmp_path / "crlf.txt").write_bytes(b"needle line\r\nnext\r\n")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "needle", "path": "crlf.txt"})

    assert result.content["matches"] == [{"path": "crlf.txt", "line": 1, "excerpt": "needle line"}]


def test_search_text_excerpt_centres_on_the_match_with_ellipsis_on_the_cut_sides(tmp_path):
    near_start = "x" * 10 + "NEEDLE" + "y" * 284
    near_end = "y" * 284 + "NEEDLE" + "x" * 10
    middle = "y" * 150 + "NEEDLE" + "y" * 150
    (tmp_path / "near_start.txt").write_text(near_start + "\n")
    (tmp_path / "near_end.txt").write_text(near_end + "\n")
    (tmp_path / "middle.txt").write_text(middle + "\n")
    workspace.configure_workspace(tmp_path)

    start_excerpt = _execute("search_text", {"text": "NEEDLE", "path": "near_start.txt"}).content["matches"][0][
        "excerpt"
    ]
    end_excerpt = _execute("search_text", {"text": "NEEDLE", "path": "near_end.txt"}).content["matches"][0][
        "excerpt"
    ]
    middle_excerpt = _execute("search_text", {"text": "NEEDLE", "path": "middle.txt"}).content["matches"][0][
        "excerpt"
    ]

    assert start_excerpt == near_start[0:200] + "…"
    assert end_excerpt == "…" + near_end[100:300]
    assert middle_excerpt == "…" + middle[53:253] + "…"
    for excerpt in (start_excerpt, end_excerpt, middle_excerpt):
        assert "NEEDLE" in excerpt


def test_search_text_line_numbers_round_trip_through_read_file(tmp_path):
    (tmp_path / "doc.txt").write_text("alpha\nneedle here\ngamma\n")
    workspace.configure_workspace(tmp_path)

    hit = _execute("search_text", {"text": "needle", "path": "doc.txt"}).content["matches"][0]
    read_back = _execute("read_file", {"path": "doc.txt", "offset": hit["line"], "limit": 1})

    assert read_back.content["content"] == f"{hit['line']}\tneedle here\n"


def test_search_text_output_bound_by_the_tool_output_cap_truncates_and_sets_truncated(tmp_path):
    (tmp_path / "many.txt").write_text("needle\n" * 50)
    workspace.configure_workspace(tmp_path, "100")

    result = _execute("search_text", {"text": "needle", "path": "many.txt"})

    assert result.content["truncated"] is True
    assert 0 < len(result.content["matches"]) < 50
    assert [match["line"] for match in result.content["matches"]] == list(
        range(1, len(result.content["matches"]) + 1)
    )


# --- Walk skip list (R1, ticket 0022-01) ------------------------------------


def test_list_files_skips_the_skipped_directory_names_below_the_root(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("app")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("venv")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("js")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "mod.pyc").write_text("cache")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {})

    assert result.content == {"files": ["src/app.py"], "truncated": False}


def test_list_files_and_search_text_still_reach_a_skipped_directory_named_explicitly(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("needle inside git config")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("needle inside venv")
    workspace.configure_workspace(tmp_path)

    assert _execute("list_files", {"path": ".git"}).content == {"files": [".git/config"], "truncated": False}
    search_result = _execute("search_text", {"text": "needle", "path": ".venv"})
    assert search_result.content["matches"] == [{"path": ".venv/lib.py", "line": 1, "excerpt": "needle inside venv"}]
    assert _execute("read_file", {"path": ".git/config"}).content == {
        "content": "1\tneedle inside git config",
        "has_more": False,
        "next_offset": None,
    }


def test_search_text_over_a_directory_skips_the_skipped_directory_names(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle here")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("needle in git")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "needle"})

    assert result.content["matches"] == [{"path": "src/app.py", "line": 1, "excerpt": "needle here"}]


# --- list_files glob pattern (R2-R3, ticket 0022-01) -----------------------


def test_list_files_pattern_without_slash_matches_the_file_name_at_any_depth(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("c")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": "*.py"})

    assert result.content == {"files": ["a.py", "nested/c.py"], "truncated": False}


def test_list_files_pattern_with_slash_matches_the_path_relative_to_the_searched_directory(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("app")
    (tmp_path / "src" / "sub").mkdir()
    (tmp_path / "src" / "sub" / "test_app.py").write_text("test")
    (tmp_path / "other.py").write_text("other")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"path": "src", "pattern": "src/**/test_*.py"})

    assert result.content == {"files": [], "truncated": False}
    result = _execute("list_files", {"path": "src", "pattern": "**/test_*.py"})
    assert result.content == {"files": ["src/sub/test_app.py"], "truncated": False}


def test_list_files_pattern_double_star_matches_zero_or_more_directories(tmp_path):
    (tmp_path / "top.py").write_text("top")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.py").write_text("deep")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": "**/*.py"})

    assert result.content == {"files": ["nested/deep.py", "top.py"], "truncated": False}


def test_list_files_pattern_star_does_not_cross_a_path_separator(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("app")
    (tmp_path / "src" / "sub").mkdir()
    (tmp_path / "src" / "sub" / "deep.py").write_text("deep")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": "src/*.py"})

    assert result.content == {"files": ["src/app.py"], "truncated": False}


def test_list_files_pattern_is_case_sensitive(tmp_path):
    (tmp_path / "App.py").write_text("a")
    (tmp_path / "app.py").write_text("a")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": "app.py"})

    assert result.content == {"files": ["app.py"], "truncated": False}


def test_list_files_pattern_filters_before_the_100_result_limit(tmp_path):
    for index in range(150):
        (tmp_path / f"file-{index:03d}.txt").write_text("x")
    for index in range(5):
        (tmp_path / f"match-{index}.py").write_text("x")
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": "*.py"})

    assert result.content == {
        "files": [f"match-{index}.py" for index in range(5)],
        "truncated": False,
    }


def test_list_files_pattern_schema_requires_min_length(tmp_path):
    workspace.configure_workspace(tmp_path)

    result = _execute("list_files", {"pattern": ""})

    assert result.is_error is True
    assert "invalid arguments" in result.content["error"]


# --- search_text glob filter (R4, ticket 0022-01) --------------------------


def test_search_text_glob_filters_walked_files_before_matching(tmp_path):
    (tmp_path / "a.py").write_text("needle here")
    (tmp_path / "b.txt").write_text("needle here too")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "needle", "glob": "*.py"})

    assert result.content["matches"] == [{"path": "a.py", "line": 1, "excerpt": "needle here"}]


def test_search_text_glob_is_ignored_when_path_names_a_file(tmp_path):
    (tmp_path / "b.txt").write_text("needle here")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "needle", "path": "b.txt", "glob": "*.py"})

    assert result.content["matches"] == [{"path": "b.txt", "line": 1, "excerpt": "needle here"}]


# --- search_text regex (R5, ticket 0022-01) ---------------------------------


def test_search_text_regex_matches_a_pattern_case_insensitively(tmp_path):
    (tmp_path / "a.py").write_text("def foo_tool():\nno match\nDEF BAR_TOOL():\n")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": r"def \w+_tool", "path": "a.py", "regex": True})

    assert result.content["matches"] == [
        {"path": "a.py", "line": 1, "excerpt": "def foo_tool():"},
        {"path": "a.py", "line": 3, "excerpt": "DEF BAR_TOOL():"},
    ]


def test_search_text_regex_anchors_work_on_a_crlf_line(tmp_path):
    (tmp_path / "crlf.txt").write_bytes(b"needle$here\r\nneedle at end\r\n")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "end$", "path": "crlf.txt", "regex": True})

    assert result.content["matches"] == [{"path": "crlf.txt", "line": 2, "excerpt": "needle at end"}]


def test_search_text_regex_excerpt_centres_on_the_first_match_in_a_long_line(tmp_path):
    line = "y" * 150 + "NEEDLE123" + "y" * 150
    (tmp_path / "long.txt").write_text(line + "\n")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": r"needle\d+", "path": "long.txt", "regex": True})

    excerpt = result.content["matches"][0]["excerpt"]
    assert "NEEDLE123" in excerpt
    assert excerpt == "…" + line[54:254] + "…"


def test_search_text_invalid_regex_is_an_error_naming_the_problem_before_any_file_is_read(tmp_path):
    (tmp_path / "a.py").write_text("x")
    workspace.configure_workspace(tmp_path)

    result = _execute("search_text", {"text": "(unterminated", "path": "a.py", "regex": True})

    assert result.is_error is True
    assert result.content["error"].startswith("invalid regex: ")


def test_workspace_tool_error_does_not_stop_another_call_in_the_batch(tmp_path):
    (tmp_path / "ok.txt").write_text("ok")
    workspace.configure_workspace(tmp_path)

    results = tools.execute_batch(
        [
            ToolCall(id="bad", name="read_file", arguments={"path": "missing.txt"}),
            ToolCall(id="good", name="list_files", arguments={}),
        ]
    )

    assert results[0].is_error is True
    assert results[1].content == {"files": ["ok.txt"], "truncated": False}


def _write(tmp_path, path, content, confirm=True):
    seen = []

    def _confirm(tool_name, display_path, preview, dangerous_rules=(), fetched_urls=()):
        seen.append((tool_name, display_path, preview))
        return confirm

    call = ToolCall(id="1", name="write", arguments={"path": path, "content": content})
    result = tools.execute_batch([call], confirm=_confirm)[0]
    return result, seen


# --- write (R21-R35, ticket 0016-01) ---------------------------------------


def test_configure_workspace_write_limit_defaults_and_rejects_invalid_limits(tmp_path):
    configured = workspace.configure_workspace(tmp_path)
    assert configured.max_write_bytes == 1024 * 1024

    with pytest.raises(ValueError, match="PA_MAX_WRITE_BYTES"):
        workspace.configure_workspace(tmp_path, None, "0")
    with pytest.raises(ValueError, match="PA_MAX_WRITE_BYTES"):
        workspace.configure_workspace(tmp_path, None, "1.5")

    configured = workspace.configure_workspace(tmp_path, None, "10")
    assert configured.max_write_bytes == 10


def test_write_tool_is_advertised_and_requires_path_and_content(tmp_path):
    workspace.configure_workspace(tmp_path)
    definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert "write" in definitions
    assert set(definitions["write"]["required"]) == {"path", "content"}
    assert definitions["write"]["properties"]["path"]["minLength"] == 1
    assert definitions["write"]["additionalProperties"] is False


def test_write_creates_a_new_file_with_full_content_preview_when_confirmed(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "new.txt", "hello\n")

    assert result.is_error is False
    assert result.content == {"path": "new.txt", "bytes_written": 6, "created": True}
    assert (tmp_path / "new.txt").read_bytes() == b"hello\n"
    assert seen == [("write", "new.txt", "hello\n")]


def test_write_overwrites_an_existing_file_with_a_unified_diff_preview_when_confirmed(tmp_path):
    (tmp_path / "existing.txt").write_text("old line\nkept line\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "existing.txt", "new line\nkept line\n")

    assert result.is_error is False
    assert result.content == {"path": "existing.txt", "bytes_written": 19, "created": False}
    assert (tmp_path / "existing.txt").read_text() == "new line\nkept line\n"
    _, display_path, preview = seen[0]
    assert display_path == "existing.txt"
    assert preview.startswith("--- existing.txt\n+++ existing.txt\n")
    assert "-old line\n" in preview
    assert "+new line\n" in preview
    assert " kept line\n" in preview


def test_write_rejected_leaves_the_file_untouched_and_returns_a_rejection_error(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, _ = _write(tmp_path, "rejected.txt", "nope", confirm=False)

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert not (tmp_path / "rejected.txt").exists()


def test_write_without_a_confirm_callback_is_rejected_without_prompting(tmp_path):
    workspace.configure_workspace(tmp_path)
    call = ToolCall(id="1", name="write", arguments={"path": "no-callback.txt", "content": "nope"})

    result = tools.execute_batch([call])[0]

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert not (tmp_path / "no-callback.txt").exists()


@pytest.mark.parametrize(
    "path, expected_error_fragment",
    [
        ("../escape.txt", "traversal"),
        ("missing-parent/child.txt", "unavailable"),
        (".env", "excluded"),
    ],
)
def test_write_validation_failures_never_call_confirm(tmp_path, path, expected_error_fragment):
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, path, "x")

    assert result.is_error is True
    assert expected_error_fragment in result.content["error"]
    assert seen == []


def test_write_rejects_an_existing_directory_target_without_calling_confirm(tmp_path):
    (tmp_path / "adir").mkdir()
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "adir", "x")

    assert result.is_error is True
    assert "must name a file" in result.content["error"]
    assert seen == []


def test_write_rejects_a_directory_symlink_parent_without_calling_confirm(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "link/child.txt", "x")

    assert result.is_error is True
    assert "symlink" in result.content["error"]
    assert seen == []


def test_write_rejects_a_dangling_symlink_target_without_calling_confirm(tmp_path):
    (tmp_path / "dangling.txt").symlink_to(tmp_path / "does-not-exist.txt")
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "dangling.txt", "x")

    assert result.is_error is True
    assert seen == []


def test_write_rejects_a_target_that_escapes_the_workspace_via_symlink(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside")
    (tmp_path / "escape-link.txt").symlink_to(outside)
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "escape-link.txt", "x")

    assert result.is_error is True
    assert "outside" in result.content["error"]
    assert seen == []


def test_write_rejects_an_existing_target_that_resolves_to_an_excluded_name(tmp_path):
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "alias.txt").symlink_to(tmp_path / ".env")
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "alias.txt", "x")

    assert result.is_error is True
    assert "excluded" in result.content["error"]
    assert seen == []


def test_write_content_over_the_limit_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path, None, "4")

    result, seen = _write(tmp_path, "big.txt", "hello")

    assert result.is_error is True
    assert "content exceeds the 4-byte write limit" in result.content["error"]
    assert seen == []
    assert not (tmp_path / "big.txt").exists()


def test_write_overwrite_of_an_existing_file_larger_than_the_read_cap_succeeds(tmp_path):
    (tmp_path / "large.txt").write_text("12345")
    workspace.configure_workspace(tmp_path, "4")

    result, seen = _write(tmp_path, "large.txt", "new content")

    assert result.is_error is False
    assert len(seen) == 1
    assert (tmp_path / "large.txt").read_text() == "new content"


def test_write_overwrite_of_an_existing_file_over_the_write_limit_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "large.txt").write_text("123456")
    workspace.configure_workspace(tmp_path, None, "4")

    result, seen = _write(tmp_path, "large.txt", "new")

    assert result.is_error is True
    assert "file exceeds the 4-byte write limit" in result.content["error"]
    assert seen == []
    assert (tmp_path / "large.txt").read_text() == "123456"


def test_write_content_not_encodable_as_utf8_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "bad.txt", "abc\udc80def")

    assert result.is_error is True
    assert "UTF-8" in result.content["error"]
    assert seen == []


def test_write_overwriting_a_binary_existing_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"x\0y")
    workspace.configure_workspace(tmp_path)

    result, seen = _write(tmp_path, "binary.bin", "text")

    assert result.is_error is True
    assert "binary" in result.content["error"]
    assert seen == []


def test_write_is_written_as_raw_bytes_with_no_newline_translation(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, _ = _write(tmp_path, "raw.txt", "line1\r\nline2\n")

    assert result.is_error is False
    assert (tmp_path / "raw.txt").read_bytes() == b"line1\r\nline2\n"


def test_write_apply_failure_is_reported_as_a_tool_error(tmp_path, monkeypatch):
    workspace.configure_workspace(tmp_path)

    def _boom(self, data):
        raise OSError("disk is full")

    monkeypatch.setattr(file_recovery, "put", _boom)

    result, seen = _write(tmp_path, "boom.txt", "x")

    assert result.is_error is True
    assert "disk is full" in result.content["error"]
    assert len(seen) == 1
    assert not (tmp_path / "boom.txt").exists()


def test_execute_batch_attaches_completed_results_to_a_mid_batch_keyboard_interrupt(tmp_path):
    workspace.configure_workspace(tmp_path)
    answers = iter([True])

    def _confirm(tool_name, display_path, preview, dangerous_rules=(), fetched_urls=()):
        if next(answers, None) is True:
            return True
        raise KeyboardInterrupt

    calls = [
        ToolCall(id="1", name="write", arguments={"path": "a.txt", "content": "a"}),
        ToolCall(id="2", name="write", arguments={"path": "b.txt", "content": "b"}),
    ]

    with pytest.raises(KeyboardInterrupt) as excinfo:
        tools.execute_batch(calls, confirm=_confirm)

    partial_results = excinfo.value.partial_results
    assert len(partial_results) == 1
    assert partial_results[0].id == "1"
    assert partial_results[0].is_error is False
    assert partial_results[0].content == {"path": "a.txt", "bytes_written": 1, "created": True}
    assert (tmp_path / "a.txt").read_text() == "a"
    assert not (tmp_path / "b.txt").exists()


# --- edit (R21-R35, ticket 0016-02) -----------------------------------------


def _edit(tmp_path, path, old_string, new_string, replace_all=False, confirm=True):
    seen = []

    def _confirm(tool_name, display_path, preview, dangerous_rules=(), fetched_urls=()):
        seen.append((tool_name, display_path, preview))
        return confirm

    arguments = {"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all}
    call = ToolCall(id="1", name="edit", arguments=arguments)
    result = tools.execute_batch([call], confirm=_confirm)[0]
    return result, seen


def test_edit_tool_is_advertised_and_requires_path_old_string_new_string(tmp_path):
    workspace.configure_workspace(tmp_path)
    definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert "edit" in definitions
    assert set(definitions["edit"]["required"]) == {"path", "old_string", "new_string"}
    assert definitions["edit"]["properties"]["path"]["minLength"] == 1
    assert definitions["edit"]["properties"]["old_string"]["minLength"] == 1
    assert definitions["edit"]["properties"]["replace_all"]["default"] is False
    assert definitions["edit"]["additionalProperties"] is False


def test_edit_replaces_the_one_occurrence_with_a_diff_preview_when_confirmed(tmp_path):
    (tmp_path / "existing.txt").write_text("old line\nkept line\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "existing.txt", "old line", "new line")

    assert result.is_error is False
    assert result.content == {"path": "existing.txt", "replacements": 1}
    assert (tmp_path / "existing.txt").read_text() == "new line\nkept line\n"
    _, display_path, preview = seen[0]
    assert display_path == "existing.txt"
    assert preview.startswith("--- existing.txt\n+++ existing.txt\n")
    assert "-old line\n" in preview
    assert "+new line\n" in preview
    assert " kept line\n" in preview


def test_edit_replace_all_replaces_every_occurrence(tmp_path):
    (tmp_path / "existing.txt").write_text("a needle b needle c\n")
    workspace.configure_workspace(tmp_path)

    result, _ = _edit(tmp_path, "existing.txt", "needle", "pin", replace_all=True)

    assert result.is_error is False
    assert result.content == {"path": "existing.txt", "replacements": 2}
    assert (tmp_path / "existing.txt").read_text() == "a pin b pin c\n"


def test_edit_with_zero_matches_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "existing.txt").write_text("no match here\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "existing.txt", "missing", "x")

    assert result.is_error is True
    assert "not found" in result.content["error"]
    assert seen == []
    assert (tmp_path / "existing.txt").read_text() == "no match here\n"


def test_edit_with_more_than_one_match_without_replace_all_is_an_error_naming_the_count(tmp_path):
    (tmp_path / "existing.txt").write_text("needle needle needle\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "existing.txt", "needle", "pin")

    assert result.is_error is True
    assert "3" in result.content["error"]
    assert seen == []
    assert (tmp_path / "existing.txt").read_text() == "needle needle needle\n"


def test_edit_is_case_sensitive_and_exact_no_fuzzy_matching(tmp_path):
    (tmp_path / "existing.txt").write_text("Needle here\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "existing.txt", "needle", "pin")

    assert result.is_error is True
    assert "not found" in result.content["error"]
    assert seen == []


def test_edit_with_new_string_equal_to_old_string_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "existing.txt").write_text("same same\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "existing.txt", "same", "same")

    assert result.is_error is True
    assert "identical" in result.content["error"]
    assert seen == []


def test_edit_rejected_leaves_the_file_untouched_and_returns_a_rejection_error(tmp_path):
    (tmp_path / "existing.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)

    result, _ = _edit(tmp_path, "existing.txt", "old", "new", confirm=False)

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert (tmp_path / "existing.txt").read_text() == "old\n"


def test_edit_without_a_confirm_callback_is_rejected_without_prompting(tmp_path):
    (tmp_path / "existing.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)
    call = ToolCall(id="1", name="edit", arguments={"path": "existing.txt", "old_string": "old", "new_string": "new"})

    result = tools.execute_batch([call])[0]

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert (tmp_path / "existing.txt").read_text() == "old\n"


def test_edit_target_must_pass_the_existing_file_target_rules(tmp_path):
    (tmp_path / ".env").write_text("secret=old\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, ".env", "secret", "public")

    assert result.is_error is True
    assert "excluded" in result.content["error"]
    assert seen == []


def test_edit_on_a_missing_file_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "missing.txt", "old", "new")

    assert result.is_error is True
    assert seen == []


def test_edit_on_a_binary_or_non_utf8_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"x\0y")
    workspace.configure_workspace(tmp_path)

    result, seen = _edit(tmp_path, "binary.bin", "x", "y")

    assert result.is_error is True
    assert "binary" in result.content["error"]
    assert seen == []


def test_edit_of_a_file_larger_than_the_read_cap_succeeds(tmp_path):
    (tmp_path / "large.txt").write_text("12345")
    workspace.configure_workspace(tmp_path, "4")

    result, seen = _edit(tmp_path, "large.txt", "1", "9")

    assert result.is_error is False
    assert len(seen) == 1
    assert (tmp_path / "large.txt").read_text() == "92345"


def test_edit_on_an_existing_file_over_the_write_limit_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "large.txt").write_text("123456")
    workspace.configure_workspace(tmp_path, None, "4")

    result, seen = _edit(tmp_path, "large.txt", "1", "9")

    assert result.is_error is True
    assert "file exceeds the 4-byte write limit" in result.content["error"]
    assert seen == []


def test_edit_resulting_content_over_the_write_limit_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "existing.txt").write_text("hi\n")
    workspace.configure_workspace(tmp_path, None, "4")

    result, seen = _edit(tmp_path, "existing.txt", "hi", "much longer replacement")

    assert result.is_error is True
    assert "write limit" in result.content["error"]
    assert seen == []
    assert (tmp_path / "existing.txt").read_text() == "hi\n"


def test_edit_apply_failure_is_reported_as_a_tool_error(tmp_path, monkeypatch):
    (tmp_path / "existing.txt").write_text("old\n")
    workspace.configure_workspace(tmp_path)

    def _boom(self, data):
        raise OSError("disk is full")

    monkeypatch.setattr(file_recovery, "put", _boom)

    result, seen = _edit(tmp_path, "existing.txt", "old", "new")

    assert result.is_error is True
    assert "disk is full" in result.content["error"]
    assert len(seen) == 1
    assert (tmp_path / "existing.txt").read_text() == "old\n"


# --- apply_patch: Update File (R1-R8, ticket 0028-01) ----------------------


def _apply_patch(tmp_path, patch, confirm=True):
    seen = []

    def _confirm(tool_name, display_path, preview, dangerous_rules=(), fetched_urls=()):
        seen.append((tool_name, display_path, preview))
        return confirm

    call = ToolCall(id="1", name="apply_patch", arguments={"patch": patch})
    result = tools.execute_batch([call], confirm=_confirm)[0]
    return result, seen


def test_apply_patch_tool_is_advertised_and_absent_from_plan(tmp_path):
    workspace.configure_workspace(tmp_path)
    build_definitions = {definition.name: definition.parameters for definition in tools.TOOL_DEFS}

    assert "apply_patch" in build_definitions
    assert build_definitions["apply_patch"]["required"] == ["patch"]
    assert build_definitions["apply_patch"]["properties"]["patch"]["minLength"] == 1
    assert build_definitions["apply_patch"]["additionalProperties"] is False
    plan_definitions = {definition.name for definition in tools.definitions_for_mode("plan")}
    assert "apply_patch" not in plan_definitions


def test_apply_patch_is_rejected_in_plan_mode_before_validation_and_confirmation(tmp_path):
    workspace.configure_workspace(tmp_path)
    seen = []

    def _confirm(tool_name, display_path, preview, dangerous_rules=(), fetched_urls=()):
        seen.append(True)
        return True

    call = ToolCall(id="1", name="apply_patch", arguments={"patch": "not even a real patch"})
    result = tools.execute_batch([call], confirm=_confirm, mode="plan")[0]

    assert result.is_error is True
    assert result.content == {"error": "tool 'apply_patch' is unavailable in plan mode"}
    assert seen == []


def _update_patch(path, hunk_body, header="*** Update File: {path}"):
    return "*** Begin Patch\n" + header.format(path=path) + "\n" + hunk_body + "*** End Patch"


def test_apply_patch_updates_one_file_with_one_hunk_and_shows_a_unified_diff(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " one\n-two\n+TWO\n three\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {"files": [{"path": "a.txt", "action": "update"}]}
    assert (tmp_path / "a.txt").read_text() == "one\nTWO\nthree\n"
    tool_name, display_path, preview = seen[0]
    assert tool_name == "apply_patch"
    assert display_path == "a.txt"
    assert preview.startswith("--- a.txt\n+++ a.txt\n")
    assert "-two\n" in preview
    assert "+TWO\n" in preview


def test_apply_patch_updates_several_files_with_several_hunks_in_one_confirmed_patch(tmp_path):
    (tmp_path / "a.txt").write_text("a1\na2\na3\na4\n")
    (tmp_path / "b.txt").write_text("b1\nb2\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        " a1\n"
        "-a2\n"
        "+A2\n"
        " a3\n"
        "@@\n"
        "-a4\n"
        "+FOUR\n"
        "*** Update File: b.txt\n"
        "-b1\n"
        " b2\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {"files": [{"path": "a.txt", "action": "update"}, {"path": "b.txt", "action": "update"}]}
    assert (tmp_path / "a.txt").read_text() == "a1\nA2\na3\nFOUR\n"
    assert (tmp_path / "b.txt").read_text() == "b2\n"
    assert seen[0][1] == "a.txt, b.txt"
    assert "a.txt" in seen[0][2] and "b.txt" in seen[0][2]


def test_apply_patch_anchor_disambiguates_repeated_context(tmp_path):
    (tmp_path / "a.txt").write_text("head\nsame\nmid\nsame\ntail\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "@@ mid\n-same\n+changed\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "head\nsame\nmid\nchanged\ntail\n"


def test_apply_patch_context_not_found_is_a_tool_error_naming_path_and_hunk(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "-missing\n+x\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert result.content["error"] == "a.txt: hunk 1: context not found"
    assert seen == []
    assert (tmp_path / "a.txt").read_text() == "one\ntwo\n"


def test_apply_patch_ambiguous_context_without_anchor_is_a_tool_error(tmp_path):
    (tmp_path / "a.txt").write_text("same\nsame\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "-same\n+changed\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert result.content["error"] == "a.txt: hunk 1: context is ambiguous, add an @@ anchor or more context"
    assert seen == []


def test_apply_patch_missing_anchor_is_a_tool_error(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "@@ nope\n-one\n+x\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "anchor not found" in result.content["error"]
    assert seen == []


def test_apply_patch_blank_at_anchor_is_treated_as_a_bare_at_at_with_no_anchor(tmp_path):
    (tmp_path / "a.txt").write_text("k\n\nk\nend\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "@@ \n-k\n+K\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert result.content["error"] == "a.txt: hunk 1: context is ambiguous, add an @@ anchor or more context"
    assert seen == []
    assert (tmp_path / "a.txt").read_text() == "k\n\nk\nend\n"


def test_apply_patch_hunks_apply_top_to_bottom_so_a_later_hunk_never_matches_above_an_earlier_one(tmp_path):
    (tmp_path / "a.txt").write_text("a\nx\nb\nx\nc\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Update File: a.txt\n a\n-x\n+first\n@@\n-x\n+second\n*** End Patch"

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "a\nfirst\nb\nsecond\nc\n"


def test_apply_patch_end_of_file_pins_the_hunk_to_the_last_line(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "-two\n+TWO\n*** End of File\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "one\ntwo\nTWO\n"


def test_apply_patch_plus_only_hunk_appends_at_the_end_of_the_file(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "+three\n+four\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "one\ntwo\nthree\nfour\n"


def test_apply_patch_empty_line_in_a_hunk_is_an_empty_context_line(tmp_path):
    (tmp_path / "a.txt").write_text("one\n\nthree\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " one\n\n-three\n+THREE\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "one\n\nTHREE\n"


def test_apply_patch_context_line_that_looks_like_an_anchor_is_not_read_as_one(tmp_path):
    (tmp_path / "a.txt").write_text("head\n@@ -1 +1 @@\ntail\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " head\n @@ -1 +1 @@\n-tail\n+TAIL\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_text() == "head\n@@ -1 +1 @@\nTAIL\n"


def test_apply_patch_preserves_crlf_line_endings(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " one\n-two\n+TWO\n three\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_bytes() == b"one\r\nTWO\r\nthree\r\n"


def test_apply_patch_adds_a_trailing_newline_when_the_original_file_lacked_one(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " one\n-two\n+TWO\n")

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert (tmp_path / "a.txt").read_bytes() == b"one\nTWO\n"


def test_apply_patch_update_preview_marks_a_missing_final_newline_on_the_old_side(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nomega")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " alpha\n-omega\n+OMEGA\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    preview = seen[0][2]
    assert "-omega\n\\ No newline at end of file\n+OMEGA\n" in preview


def test_apply_patch_preview_keeps_a_form_feed_mid_line_as_one_line(tmp_path):
    (tmp_path / "a.txt").write_text("a\x0cb\nc\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " a\x0cb\n-c\n+C\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    preview = seen[0][2]
    assert " a\x0cb\n" in preview
    assert "\\ No newline at end of file" not in preview


def test_apply_patch_delete_without_a_final_newline_does_not_glue_into_the_next_block(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo")
    (tmp_path / "b.txt").write_text("x\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Delete File: a.txt\n"
        "*** Update File: b.txt\n"
        "-x\n"
        "+y\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    preview = seen[0][2]
    assert "-two\n\\ No newline at end of file\n--- b.txt" in preview


def test_apply_patch_no_op_update_is_a_tool_error_before_confirm_is_called(tmp_path):
    (tmp_path / "a.txt").write_text("same\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", " same\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "no changes" in result.content["error"]
    assert seen == []


@pytest.mark.parametrize(
    "patch, fragment",
    [
        ("no markers at all", "Begin Patch"),
        ("*** Begin Patch\n*** End Patch", "no file sections"),
        ("*** Begin Patch\n*** Update File: a.txt\n*** End Patch", "no hunks"),
        ("*** Begin Patch\n*** Update File: a.txt\n@@\n*** End Patch", "empty"),
        ("*** Begin Patch\n*** Move to: b.txt\n*** End Patch", "Move to is not supported"),
        ("*** Begin Patch\nnonsense line\n*** End Patch", "unrecognized line"),
    ],
)
def test_apply_patch_grammar_errors_are_tool_errors_before_confirm_is_called(tmp_path, patch, fragment):
    (tmp_path / "a.txt").write_text("content\n")
    workspace.configure_workspace(tmp_path)

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert fragment in result.content["error"]
    assert seen == []


@pytest.mark.parametrize(
    "path, fragment",
    [
        ("../escape.txt", "traversal"),
        ("missing.txt", "unavailable"),
        (".env", "excluded"),
    ],
)
def test_apply_patch_update_bounds_failures_never_call_confirm(tmp_path, path, fragment):
    (tmp_path / ".env").write_text("secret\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch(path, " x\n-y\n+z\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert fragment in result.content["error"]
    assert seen == []


def test_apply_patch_update_target_over_the_write_limit_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "big.txt").write_text("123456\n")
    workspace.configure_workspace(tmp_path, None, "4")
    patch = _update_patch("big.txt", "-123456\n+1\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "write limit" in result.content["error"]
    assert seen == []


def test_apply_patch_binary_update_target_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"x\0y")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("binary.bin", "-x\n+y\n")

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "binary" in result.content["error"]
    assert seen == []


def test_apply_patch_duplicate_path_in_one_patch_is_a_tool_error(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        "-one\n"
        "+ONE\n"
        "*** Update File: a.txt\n"
        "-two\n"
        "+TWO\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "duplicate path" in result.content["error"]
    assert seen == []


def test_apply_patch_duplicate_via_symlink_alias_is_a_tool_error(tmp_path):
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "alias.txt").symlink_to(tmp_path / "a.txt")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        "-one\n"
        "+ONE\n"
        "*** Update File: alias.txt\n"
        "-one\n"
        "+ONE2\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "duplicate path" in result.content["error"]
    assert seen == []


def test_apply_patch_add_duplicate_via_directory_symlink_alias_is_a_tool_error(tmp_path):
    (tmp_path / "d" / "sub").mkdir(parents=True)
    (tmp_path / "dl").symlink_to(tmp_path / "d")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Add File: d/sub/n.txt\n"
        "+one\n"
        "*** Add File: dl/sub/n.txt\n"
        "+two\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "duplicate path" in result.content["error"]
    assert seen == []
    assert not (tmp_path / "d" / "sub" / "n.txt").exists()


def test_apply_patch_rejected_leaves_every_file_untouched(tmp_path):
    (tmp_path / "a.txt").write_text("one\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "-one\n+ONE\n")

    result, seen = _apply_patch(tmp_path, patch, confirm=False)

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert (tmp_path / "a.txt").read_text() == "one\n"
    assert len(seen) == 1


def test_apply_patch_without_a_confirm_callback_is_rejected_without_prompting(tmp_path):
    (tmp_path / "a.txt").write_text("one\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("a.txt", "-one\n+ONE\n")
    call = ToolCall(id="1", name="apply_patch", arguments={"patch": patch})

    result = tools.execute_batch([call])[0]

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert (tmp_path / "a.txt").read_text() == "one\n"


def test_apply_patch_mid_apply_failure_on_the_second_file_restores_the_first_and_the_failing_one(
    tmp_path, monkeypatch
):
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "b.txt").write_text("two\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        "-one\n"
        "+ONE\n"
        "*** Update File: b.txt\n"
        "-two\n"
        "+TWO\n"
        "*** End Patch"
    )
    original_put = file_recovery.put

    def _boom(identity, state):
        if identity["supplied"] == "b.txt":
            raise OSError("disk is full")
        return original_put(identity, state)

    monkeypatch.setattr(file_recovery, "put", _boom)

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "b.txt" in result.content["error"]
    assert "disk is full" in result.content["error"]
    assert len(seen) == 1
    assert (tmp_path / "a.txt").read_text() == "one\n"
    assert (tmp_path / "b.txt").read_text() == "two\n"


def test_apply_patch_restore_failure_is_reported_in_the_tool_error(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "b.txt").write_text("two\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: a.txt\n"
        "-one\n"
        "+ONE\n"
        "*** Update File: b.txt\n"
        "-two\n"
        "+TWO\n"
        "*** End Patch"
    )
    original_put = file_recovery.put

    def _boom(identity, state):
        if identity["supplied"] == "b.txt":
            raise OSError("disk is full")
        if identity["supplied"] == "a.txt" and file_recovery._bytes(state) == b"one\n":
            raise OSError("restore also failed")
        return original_put(identity, state)

    monkeypatch.setattr(file_recovery, "put", _boom)

    result, _ = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "could not restore: a.txt" in result.content["error"]


def test_apply_patch_result_reaches_provider_follow_up_and_call_log(tmp_path, route_env, install_fake_urlopen):
    (tmp_path / "note.txt").write_text("before\n")
    workspace.configure_workspace(tmp_path)
    patch = _update_patch("note.txt", "-before\n+after\n")
    calls = install_fake_urlopen(
        [
            {"tool_calls": [{"id": "call_1", "name": "apply_patch", "arguments": {"patch": patch}}]},
            "patched",
        ]
    )

    from personal_agent.routing.router import route

    result = route("apply the patch", runtime_config.load(), confirm=lambda *args, **kwargs: True)

    assert result.ok is True
    assert (tmp_path / "note.txt").read_text() == "after\n"
    body = json.loads(calls[1]["request"].data)
    tool_messages = [message["content"] for message in body["messages"] if message["role"] == "tool"]
    expected_result = {"files": [{"path": "note.txt", "action": "update"}]}
    assert json.dumps(expected_result) in tool_messages
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    tool_line = next(entry for entry in entries if entry["type"] == "tool_execution")
    assert tool_line["name"] == "apply_patch"
    assert tool_line["result"] == expected_result


# --- apply_patch: Add File and Delete File (R2, R4-R8, ticket 0028-02) ----


def test_apply_patch_adds_a_new_file_with_the_given_content(tmp_path):
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: new.txt\n+one\n+two\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {"files": [{"path": "new.txt", "action": "add"}]}
    assert (tmp_path / "new.txt").read_text() == "one\ntwo\n"
    tool_name, display_path, preview = seen[0]
    assert display_path == "new.txt"
    assert preview == "--- /dev/null\n+++ new.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n"


def test_apply_patch_adds_an_empty_file_with_headers_only_preview(tmp_path):
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: empty.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {"files": [{"path": "empty.txt", "action": "add"}]}
    assert (tmp_path / "empty.txt").read_text() == ""
    assert seen[0][2] == "--- /dev/null\n+++ empty.txt\n"


def test_apply_patch_deletes_a_file_and_shows_it_as_all_removed(tmp_path):
    (tmp_path / "gone.txt").write_text("one\ntwo\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: gone.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {"files": [{"path": "gone.txt", "action": "delete"}]}
    assert not (tmp_path / "gone.txt").exists()
    assert seen[0][2] == "--- gone.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-one\n-two\n"


def test_apply_patch_deletes_an_empty_file_with_headers_only_preview(tmp_path):
    (tmp_path / "empty.txt").write_bytes(b"")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: empty.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert not (tmp_path / "empty.txt").exists()
    assert seen[0][2] == "--- empty.txt\n+++ /dev/null\n"


def test_apply_patch_add_update_and_delete_combine_in_one_patch_and_preview(tmp_path):
    (tmp_path / "update.txt").write_text("old\n")
    (tmp_path / "delete.txt").write_text("bye\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Add File: add.txt\n"
        "+hi\n"
        "*** Update File: update.txt\n"
        "-old\n"
        "+new\n"
        "*** Delete File: delete.txt\n"
        "*** End Patch"
    )

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is False
    assert result.content == {
        "files": [
            {"path": "add.txt", "action": "add"},
            {"path": "update.txt", "action": "update"},
            {"path": "delete.txt", "action": "delete"},
        ]
    }
    assert (tmp_path / "add.txt").read_text() == "hi\n"
    assert (tmp_path / "update.txt").read_text() == "new\n"
    assert not (tmp_path / "delete.txt").exists()
    assert seen[0][1] == "add.txt, update.txt, delete.txt"
    preview = seen[0][2]
    assert preview.index("--- /dev/null\n+++ add.txt") < preview.index("--- update.txt\n+++ update.txt")
    assert preview.index("--- update.txt\n+++ update.txt") < preview.index("--- delete.txt\n+++ /dev/null")


@pytest.mark.parametrize(
    "patch, fragment",
    [
        ("*** Begin Patch\n*** Add File: new.txt\nnot a plus line\n*** End Patch", "must start with '+'"),
    ],
)
def test_apply_patch_add_body_grammar_error_names_the_line(tmp_path, patch, fragment):
    workspace.configure_workspace(tmp_path)

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert fragment in result.content["error"]
    assert seen == []


def test_apply_patch_add_into_a_missing_directory_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: missing-dir/new.txt\n+hi\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert seen == []
    assert not (tmp_path / "missing-dir").exists()


def test_apply_patch_add_over_an_existing_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "existing.txt").write_text("here\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: existing.txt\n+hi\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "file exists; use Update File" in result.content["error"]
    assert seen == []
    assert (tmp_path / "existing.txt").read_text() == "here\n"


def test_apply_patch_add_over_a_dangling_symlink_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "dangling.txt").symlink_to(tmp_path / "does-not-exist.txt")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: dangling.txt\n+hi\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "file exists; use Update File" in result.content["error"]
    assert seen == []


def test_apply_patch_add_of_an_excluded_name_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: .env\n+SECRET=1\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "excluded" in result.content["error"]
    assert seen == []


def test_apply_patch_add_content_over_the_write_limit_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path, None, "4")
    patch = "*** Begin Patch\n*** Add File: big.txt\n+hello\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "write limit" in result.content["error"]
    assert seen == []
    assert not (tmp_path / "big.txt").exists()


def test_apply_patch_delete_of_a_missing_file_is_an_error_before_confirm_is_called(tmp_path):
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: missing.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert seen == []


def test_apply_patch_delete_of_a_symlink_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "real.txt").write_text("real\n")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: link.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "symlink" in result.content["error"]
    assert seen == []
    assert (tmp_path / "link.txt").exists()
    assert (tmp_path / "real.txt").exists()


def test_apply_patch_delete_of_an_excluded_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / ".env").write_text("secret\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: .env\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "excluded" in result.content["error"]
    assert seen == []


def test_apply_patch_delete_of_a_binary_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"x\0y")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: binary.bin\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "binary" in result.content["error"]
    assert seen == []


def test_apply_patch_delete_of_an_over_limit_file_is_an_error_before_confirm_is_called(tmp_path):
    (tmp_path / "large.txt").write_text("123456\n")
    workspace.configure_workspace(tmp_path, None, "4")
    patch = "*** Begin Patch\n*** Delete File: large.txt\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "write limit" in result.content["error"]
    assert seen == []
    assert (tmp_path / "large.txt").exists()


def test_apply_patch_same_path_as_add_and_delete_is_a_tool_error(tmp_path):
    (tmp_path / "x.txt").write_text("x\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Delete File: x.txt\n*** Add File: x.txt\n+new\n*** End Patch"

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "duplicate path" in result.content["error"]
    assert seen == []
    assert (tmp_path / "x.txt").read_text() == "x\n"


def test_apply_patch_rejection_of_add_and_delete_leaves_every_file_as_it_was(tmp_path):
    (tmp_path / "delete.txt").write_text("bye\n")
    workspace.configure_workspace(tmp_path)
    patch = "*** Begin Patch\n*** Add File: add.txt\n+hi\n*** Delete File: delete.txt\n*** End Patch"

    result, _ = _apply_patch(tmp_path, patch, confirm=False)

    assert result.is_error is True
    assert result.content == {"error": "change rejected by the user"}
    assert not (tmp_path / "add.txt").exists()
    assert (tmp_path / "delete.txt").read_text() == "bye\n"


def test_apply_patch_mid_apply_failure_after_an_add_and_a_delete_restores_both(tmp_path, monkeypatch):
    (tmp_path / "delete.txt").write_text("bye\n")
    (tmp_path / "boom.txt").write_text("x\n")
    workspace.configure_workspace(tmp_path)
    patch = (
        "*** Begin Patch\n"
        "*** Add File: add.txt\n"
        "+hi\n"
        "*** Delete File: delete.txt\n"
        "*** Update File: boom.txt\n"
        "-x\n"
        "+y\n"
        "*** End Patch"
    )
    original_put = file_recovery.put

    def _boom(identity, state):
        if identity["supplied"] == "boom.txt":
            raise OSError("disk is full")
        return original_put(identity, state)

    monkeypatch.setattr(file_recovery, "put", _boom)

    result, seen = _apply_patch(tmp_path, patch)

    assert result.is_error is True
    assert "boom.txt" in result.content["error"]
    assert len(seen) == 1
    assert not (tmp_path / "add.txt").exists()
    assert (tmp_path / "delete.txt").read_text() == "bye\n"
    assert (tmp_path / "boom.txt").read_text() == "x\n"


def test_workspace_tool_result_reaches_provider_follow_up_and_call_log(tmp_path, route_env, install_fake_urlopen):
    (tmp_path / "note.txt").write_text("from workspace")
    workspace.configure_workspace(tmp_path)
    calls = install_fake_urlopen(
        [
            {"tool_calls": [{"id": "file_1", "name": "read_file", "arguments": {"path": "note.txt"}}]},
            "grounded answer",
        ]
    )

    from personal_agent.routing.router import route

    result = route("read the note", runtime_config.load())

    assert result.ok is True
    expected_result = {"content": "1\tfrom workspace", "has_more": False, "next_offset": None}
    body = json.loads(calls[1]["request"].data)
    tool_messages = [message["content"] for message in body["messages"] if message["role"] == "tool"]
    assert json.dumps(expected_result) in tool_messages
    entries = [json.loads(line) for line in Path(call_log.session_log_path()).read_text().splitlines()]
    tool_line = next(entry for entry in entries if entry["type"] == "tool_execution")
    assert tool_line["name"] == "read_file"
    assert tool_line["result"] == expected_result
