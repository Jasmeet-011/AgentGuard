import pytest

from agentguard.config import Settings


def test_settings_loads_with_dummy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-key-for-tests")
    settings = Settings()
    assert settings.generator_model == "claude-sonnet-5"
    assert "sk-dummy-key-for-tests" not in str(settings)
    assert "**********" in str(settings)
