from app.config import Settings


def test_settings_accepts_standard_openai_key_from_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SOLVENTO_OPENAI_API_KEY", raising=False)

    assert Settings().resolved_openai_api_key == "test-key"
