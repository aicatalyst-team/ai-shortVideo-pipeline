from __future__ import annotations


def test_inspector_does_not_block_legacy_generic_true_response(monkeypatch):
    import layers.L3_visual.text_artifact_guard as module

    monkeypatch.setattr(
        module,
        "call_glm4v",
        lambda path, prompt: '{"has_artifacts": true, "reason": "garbled UI letters on the right"}',
    )

    report = module.inspect_text_artifacts("frame.jpg")

    assert report.has_artifacts is False
    assert report.confidence == 0.0
    assert report.evidence == ""


def test_inspector_blocks_high_confidence_evidenced_artifact(monkeypatch):
    import layers.L3_visual.text_artifact_guard as module

    monkeypatch.setattr(
        module,
        "call_glm4v",
        lambda path, prompt: (
            '{"has_artifacts": true, "artifact_type": "logo", "confidence": 0.93, '
            '"evidence": "clear apple-like logo on shirt", "reason": "visible brand-like mark"}'
        ),
    )

    report = module.inspect_text_artifacts("frame.jpg")

    assert report.has_artifacts is True
    assert report.artifact_type == "logo"
    assert report.confidence == 0.93
    assert "logo" in report.evidence
