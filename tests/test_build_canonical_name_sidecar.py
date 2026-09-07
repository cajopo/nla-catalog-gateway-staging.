from __future__ import annotations

import csv
import io
import json
import runpy
import sys
from pathlib import Path

import pytest
from scripts import build_canonical_name_sidecar as cli

from nla_catalog_gateway.canonical_names import CANONICAL_GAME_ORDER, CSV_HEADER, MANIFEST_FILENAME

CODE_SHA = "c" * 40


def _write_csv(path: Path) -> None:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    path.write_bytes(output.getvalue().encode())


def _arguments(tmp_path: Path, output: Path) -> list[str]:
    arguments: list[str] = []
    for option in ("magic", "pokemon", "yugioh", "one-piece"):
        path = tmp_path / f"{option}.csv"
        _write_csv(path)
        arguments.extend((f"--{option}", str(path)))
    return [*arguments, "--output", str(output), "--generator-code-sha", CODE_SHA]


def test_parse_args_maps_all_four_fixed_games(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    args = cli.parse_args(_arguments(tmp_path, output))
    assert args.magic == tmp_path / "magic.csv"
    assert args.pokemon == tmp_path / "pokemon.csv"
    assert args.yugioh == tmp_path / "yugioh.csv"
    assert args.one_piece == tmp_path / "one-piece.csv"
    assert args.output == output
    assert args.generator_code_sha == CODE_SHA


def test_main_builds_outside_repository_and_prints_value_free_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "bundle"
    assert cli.main(_arguments(tmp_path, output)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    printed = json.loads(captured.out)
    assert printed["generatorCodeSha"] == CODE_SHA
    assert [source["game"] for source in printed["sources"]] == [
        game.value for game in CANONICAL_GAME_ORDER
    ]
    assert (output / MANIFEST_FILENAME).read_text(encoding="utf-8") == captured.out.rstrip("\n")


def test_main_rejects_repository_output_and_bad_input_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "REPOSITORY_ROOT", tmp_path)
    args = _arguments(tmp_path, tmp_path / "inside")
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "canonical-name sidecar rejected\n"

    monkeypatch.setattr(cli, "REPOSITORY_ROOT", tmp_path / "elsewhere")
    args[-1] = "invalid"
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "canonical-name sidecar rejected\n"


def test_output_boundary_returns_false_when_resolution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_resolve(_self: Path, *, strict: bool = False) -> Path:
        del strict
        raise OSError

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    assert not cli._output_is_outside_repository(tmp_path / "bundle")


def test_module_entrypoint_exits_with_main_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "bundle"
    monkeypatch.setattr(sys, "argv", [str(Path(cli.__file__)), *_arguments(tmp_path, output)])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(Path(cli.__file__)), run_name="__main__")
    assert json.loads(capsys.readouterr().out)["schemaVersion"] == 1
