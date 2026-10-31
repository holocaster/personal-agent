from dataclasses import FrozenInstanceError

import pytest

from personal_agent.project_instructions import load


def test_exact_claude_bracket_reference_recurses_and_preserves_provenance(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("[@Narquia.md]")
    (tmp_path / "Narquia.md").write_text("Before @subdir/rules After", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir/rules").write_text("Regra única", encoding="utf-8")
    result = load(tmp_path)
    assert result.sources == ("CLAUDE.md", "Narquia.md", "subdir/rules")
    assert result.text == (
        "[Project source: CLAUDE.md]\n[Project source: Narquia.md]\nBefore "
        "[Project source: subdir/rules]\nRegra única\n[End project source: subdir/rules]\n"
        " After\n[End project source: Narquia.md]\n\n[End project source: CLAUDE.md]\n"
    )
    with pytest.raises(FrozenInstanceError):
        result.text = "changed"


def test_root_selection_absence_precedence_empty_and_invalid_existing(tmp_path):
    from personal_agent.project_instructions import LoadError
    assert load(tmp_path).text == ""
    assert load(tmp_path).sources == ()
    (tmp_path / "CLAUDE.md").write_text("fallback")
    (tmp_path / "AGENTS.md").write_text("")
    assert load(tmp_path).sources == ("AGENTS.md",)
    assert "fallback" not in load(tmp_path).text
    (tmp_path / "AGENTS.md").unlink()
    assert "fallback" in load(tmp_path).text
    (tmp_path / "AGENTS.md").symlink_to(tmp_path / "missing")
    with pytest.raises(LoadError):
        load(tmp_path)
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").mkdir()
    with pytest.raises(LoadError, match="regular file"):
        load(tmp_path)


def test_quoted_unicode_source_relative_parent_alias_and_depth_first_order(tmp_path):
    (tmp_path / "AGENTS.md").write_text('@sub/first [@"ação [x].txt"] @alias @sub/first', encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/first").write_text("FIRST (@'../plain rules') LAST")
    (tmp_path / "plain rules").write_text("PARENT")
    (tmp_path / "ação [x].txt").write_text("UNICODE")
    (tmp_path / "alias").symlink_to(tmp_path / "plain rules")
    result = load(tmp_path)
    assert result.sources == ("AGENTS.md", "sub/first", "plain rules", "ação [x].txt")
    assert result.text.count("FIRST") == result.text.count("PARENT") == 1
    assert result.text.index("FIRST") < result.text.index("PARENT") < result.text.index("LAST") < result.text.index("UNICODE")


def test_quote_escaping_and_literal_shell_characters(tmp_path):
    names = ['a"b', "a'b", r"a\b", '$VAR', '~rules', 'a,b.']
    (tmp_path / "AGENTS.md").write_text(r'''@"a\"b" @'a\'b' @"a\\b" @$VAR @~rules @a,b.''')
    for index, name in enumerate(names):
        (tmp_path / name).write_text(f"RULE{index}")
    assert load(tmp_path).sources == ("AGENTS.md", *names)


def test_emails_uri_fragments_fences_inline_and_isolated_at_remain_literal(tmp_path):
    literal = (
        "person@example.com https://example.test/@missing @\n"
        "`@missing` ``@missing ` inside``\n"
        "   ```python\n[@missing]\n``\n   ````\n"
        "~~~\n@missing\n~~~~  \n"
    )
    (tmp_path / "AGENTS.md").write_text(literal + "@rules\n~~~~\n@missing")
    (tmp_path / "rules").write_text("INCLUDED")
    result = load(tmp_path)
    assert literal in result.text
    assert "INCLUDED" in result.text
    assert "~~~~\n@missing" in result.text
    assert result.sources == ("AGENTS.md", "rules")


def test_unmatched_inline_backticks_remain_literal_and_do_not_hide_imports(tmp_path):
    (tmp_path / "AGENTS.md").write_text("` unmatched @rules")
    (tmp_path / "rules").write_text("INCLUDED")
    assert "` unmatched [Project source: rules]" in load(tmp_path).text


@pytest.mark.parametrize("text", ['[@]', '@""', "@''", '[@rules', '[@"rules"', '@"rules', "@'rules", '[@rules ]'])
def test_malformed_recognized_forms_fail_visibly(tmp_path, text):
    from personal_agent.project_instructions import LoadError
    (tmp_path / "AGENTS.md").write_text(text)
    with pytest.raises(LoadError) as caught:
        load(tmp_path)
    assert caught.value.source == "AGENTS.md"
    assert caught.value.reference is not None


@pytest.mark.parametrize("kind", ["parent", "absolute", "uri", "symlink", "named_env", "named_pem", "named_key", "target_env", "target_pem", "directory", "fifo", "missing", "utf8", "nul", "unreadable"])
def test_confined_regular_utf8_sources_are_required(tmp_path, monkeypatch, kind):
    import os
    from pathlib import Path
    from personal_agent.project_instructions import LoadError
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("OUTSIDE")
    reference = "rules"
    if kind in {"parent", "absolute", "uri"}:
        reference = {"parent": "../outside", "absolute": str(outside), "uri": "https://example.test/rules"}[kind]
    elif kind == "symlink":
        (root / reference).symlink_to(outside)
    elif kind.startswith("named_"):
        reference = {"named_env": ".env", "named_pem": "secret.pem", "named_key": "secret.key"}[kind]
        (root / reference).write_text("SECRET")
    elif kind.startswith("target_"):
        target = root / (".env" if kind == "target_env" else "secret.pem")
        target.write_text("SECRET")
        (root / reference).symlink_to(target)
    elif kind == "directory":
        (root / reference).mkdir()
    elif kind == "fifo":
        os.mkfifo(root / reference)
    elif kind == "utf8":
        (root / reference).write_bytes(b"\xff")
    elif kind == "nul":
        (root / reference).write_bytes(b"a\0b")
    elif kind == "unreadable":
        (root / reference).write_text("TEXT")
        original = Path.open
        def denied(path, *args, **kwargs):
            if path.name == reference:
                raise PermissionError("permission denied")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "open", denied)
    (root / "AGENTS.md").write_text(f"@{reference}")
    with pytest.raises(LoadError) as caught:
        load(root)
    assert caught.value.source == "AGENTS.md"
    assert caught.value.reference == reference
    assert caught.value.reason


@pytest.mark.parametrize("name", [".pem", ".key"])
@pytest.mark.parametrize("kind", ["direct", "alias", "named_symlink", "agents_symlink", "claude_symlink"])
def test_excluded_hidden_names_fail_for_imports_and_selected_roots(tmp_path, name, kind):
    from personal_agent.project_instructions import LoadError
    root_name = "CLAUDE.md" if kind == "claude_symlink" else "AGENTS.md"
    reference = "rules" if kind == "alias" else name
    if kind == "named_symlink":
        (tmp_path / "rules").write_text("SAFE")
        (tmp_path / name).symlink_to(tmp_path / "rules")
    else:
        (tmp_path / name).write_text("EXCLUDED")
    if kind in {"agents_symlink", "claude_symlink"}:
        (tmp_path / root_name).symlink_to(tmp_path / name)
        reference = None
        if root_name == "AGENTS.md":
            (tmp_path / "CLAUDE.md").write_text("FALLBACK")
    else:
        if kind == "alias":
            (tmp_path / reference).symlink_to(tmp_path / name)
        (tmp_path / root_name).write_text(f"@{reference}")
    with pytest.raises(LoadError, match="excluded instruction file") as caught:
        load(tmp_path)
    assert caught.value.source == root_name
    assert caught.value.reference == reference


def test_canonical_alias_cycle_names_the_chain(tmp_path):
    from personal_agent.project_instructions import LoadError
    (tmp_path / "AGENTS.md").write_text("@rules")
    (tmp_path / "rules").write_text("@alias")
    (tmp_path / "alias").symlink_to(tmp_path / "AGENTS.md")
    with pytest.raises(LoadError, match="AGENTS.md -> rules -> AGENTS.md"):
        load(tmp_path)


@pytest.mark.parametrize("bound", ["file", "aggregate", "count", "depth", "expanded"])
def test_fixed_bounds_fail_completely(tmp_path, bound):
    from personal_agent.project_instructions import LoadError
    expected = {"file": "64 KiB", "aggregate": "256 KiB", "count": "64 distinct", "depth": "16 files", "expanded": "512 KiB"}[bound]
    if bound == "file":
        (tmp_path / "AGENTS.md").write_bytes(b"x" * (65536 + 1))
    elif bound == "aggregate":
        (tmp_path / "AGENTS.md").write_text("@a @b @c @d")
        for name in "abcd":
            (tmp_path / name).write_bytes(b"x" * 65536)
    elif bound == "count":
        (tmp_path / "AGENTS.md").write_text(" ".join(f"@f{i}" for i in range(64)))
        for index in range(64):
            (tmp_path / f"f{index}").write_text("x")
    elif bound == "depth":
        (tmp_path / "AGENTS.md").write_text("@f0")
        for index in range(16):
            (tmp_path / f"f{index}").write_text(f"@f{index + 1}" if index < 15 else "x")
    else:
        deep = tmp_path
        for index in range(14):
            deep /= "d" * 240
        deep.mkdir(parents=True)
        (tmp_path / "AGENTS.md").write_text("@" + (deep / "first").relative_to(tmp_path).as_posix())
        (deep / "first").write_text(" ".join(f"@f{i}" for i in range(62)))
        for index in range(62):
            (deep / f"f{index}").write_text("x" * 1800)
    with pytest.raises(LoadError, match=expected):
        load(tmp_path)


def test_reads_are_bounded_even_without_large_file_metadata(tmp_path, monkeypatch):
    from io import BytesIO
    from pathlib import Path
    from personal_agent.project_instructions import LoadError
    (tmp_path / "AGENTS.md").write_text("small metadata")
    amounts = []
    class GrowingFile(BytesIO):
        def read(self, size=-1):
            amounts.append(size)
            assert 0 < size <= 65537
            return b"x" * size
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: GrowingFile())
    with pytest.raises(LoadError, match="64 KiB"):
        load(tmp_path)
    assert amounts == [65537]


def test_exact_file_count_depth_and_source_byte_bounds_are_accepted(tmp_path):
    (tmp_path / "AGENTS.md").write_text("@f0")
    for index in range(15):
        (tmp_path / f"f{index}").write_text(f"@f{index + 1}" if index < 14 else "x" * 65536)
    assert len(load(tmp_path).sources) == 16
    (tmp_path / "AGENTS.md").write_text(" ".join(f"@f{i}" for i in range(63)))
    for index in range(63):
        (tmp_path / f"f{index}").write_text("x")
    assert len(load(tmp_path).sources) == 64
    (tmp_path / "AGENTS.md").write_text("@a @b @c @d")
    for name in "abc":
        (tmp_path / name).write_bytes(b"x" * 65536)
    (tmp_path / "d").write_bytes(b"x" * (65536 - 11))
    assert len(load(tmp_path).sources) == 5


def test_inline_delimiters_do_not_cross_fenced_code_boundaries(tmp_path):
    literal = '` unmatched\n```\ncode ` @missing\n```\n'
    (tmp_path / 'AGENTS.md').write_text(literal + '@rules')
    (tmp_path / 'rules').write_text('INCLUDED')
    result = load(tmp_path)
    assert literal in result.text
    assert result.sources == ('AGENTS.md', 'rules')
