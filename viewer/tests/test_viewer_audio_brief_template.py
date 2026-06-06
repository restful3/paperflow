from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "viewer.html"

def test_brief_wiring_present_in_template():
    html = TPL.read_text(encoding="utf-8")
    for token in [
        "hasMdKoAudioBrief", "mdKoAudioBriefContent", "audioUsesBrief",
        "activeAudioApiType", "toggleAudioFull", "/md-ko-audio-brief",
        "'md-ko-audio-brief'", "!audioUsesBrief", "pf-audiofull-", "hasAudioText",
    ]:
        assert token in html, f"missing brief wiring token: {token}"

def test_brief_wiring_is_actually_connected():
    """Token presence isn't enough — assert the load/guard/gating is wired so a
    stale `hasMdKoAudio`-only branch can't pass silently (Codex review)."""
    html = TPL.read_text(encoding="utf-8")
    # load branch gates on hasAudioText (not bare hasMdKoAudio)
    assert "this.audioMode && this.hasAudioText" in html
    # mp3 player + generate regions gated to full-only (player, generating, 미생성, mobile btn)
    assert html.count("!audioUsesBrief") >= 4
    # 전체 switch shown only when BOTH brief and full exist
    assert "hasMdKoAudioBrief && hasMdKoAudio" in html
    # first-view auto-default + per-paper restore widened to hasAudioText
    assert "this.hasAudioText && audioPref" in html
    assert "this.hasAudioText && localStorage.getItem('pf-audio-'" in html
