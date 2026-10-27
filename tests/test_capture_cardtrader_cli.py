import json
import sys

import pytest
from scripts import capture_cardtrader_catalog as cli


@pytest.mark.parametrize("case", ["success", "invalid_json", "invalid_token", "capture_error"])
@pytest.mark.parametrize("scope", ["legacy", "six-games"])
def test_cli_uses_private_file_and_never_prints_token(tmp_path, monkeypatch, capsys, case, scope):
    secret = "test-only-secret"  # noqa: S105 -- synthetic log-redaction sentinel
    credential = tmp_path / "credential.json"
    credential.write_text(
        json.dumps({"api_token": secret if case != "invalid_token" else ""})
        if case != "invalid_json"
        else secret
    )
    credential.chmod(0o600)
    output = tmp_path / "capture"
    argv = ["capture", "--credential-file", str(credential), "--output", str(output)]
    if scope != "legacy":
        argv.extend(["--game-scope", scope])
    monkeypatch.setattr(sys, "argv", argv)

    def capture(client, destination, *, game_scope):
        assert destination == output
        assert game_scope == scope
        if case == "capture_error":
            raise RuntimeError(secret)
        return {"status": "complete", "shopifyChanged": False, "files": {"never_print": secret}}

    monkeypatch.setattr(cli, "capture_catalog", capture)
    assert cli.main() == (0 if case == "success" else 1)
    text = capsys.readouterr().out
    assert secret not in text and "never_print" not in text
    assert json.loads(text)["status"] == ("complete" if case == "success" else "capture_failed")
