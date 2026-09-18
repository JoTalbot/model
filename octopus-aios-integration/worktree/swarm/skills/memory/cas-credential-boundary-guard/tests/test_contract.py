import ast
from pathlib import Path

def test_guard_never_serializes_token_values():
    src=Path(__file__).resolve().parents[1]/'code'/'run.py'
    text=src.read_text()
    tree=ast.parse(text)
    assert "secret_values_emitted" in text
    assert "'secret_values_emitted':False" in text.replace(' ','')
    assert "print(vals" not in text
    assert "print(tmap" not in text

def test_guard_checks_auth_and_process_boundary():
    text=(Path(__file__).resolve().parents[1]/'code'/'run.py').read_text()
    for marker in ('no_inline_systemd_tokens','no_tokens_in_process_env','unauth_denied','wrong_denied','read_token_allowed','loopback_listener'):
        assert marker in text
