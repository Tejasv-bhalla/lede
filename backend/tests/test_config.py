from app.config import Settings


def test_blank_entries_in_env_fall_back_to_defaults(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=            # https://console.groq.com/keys\nDATABASE_URL=\n")
    for name in ("GROQ_API_KEY", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=env)  # type: ignore[call-arg]

    assert settings.groq_api_key is None
    assert settings.database_url.startswith("sqlite")
