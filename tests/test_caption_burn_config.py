from __future__ import annotations


def test_caption_burn_is_disabled_by_default():
    from config.settings import Settings

    assert Settings().enable_burn_captions is False


def test_caption_burn_helper_reads_settings(monkeypatch):
    import api.webhooks as webhooks

    class DummySettings:
        enable_burn_captions = True

    monkeypatch.setattr(webhooks, "get_settings", lambda: DummySettings())

    assert webhooks._caption_burn_enabled() is True
