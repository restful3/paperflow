"""Regression guards for the audio player UI in viewer.html.

These read the template as text (the project has no JS test harness — visual/Alpine
behavior is verified in-app). They lock in the two evidence-backed defects fixed after a
live repro: (1) the generate-status UI promised auto-play that was never wired, and
(2) the play button flipped to ⏸ on play() request instead of on actual playback start.
"""
from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "app" / "templates" / "viewer.html"


def test_audio_status_does_not_promise_autoplay():
    # The generate-status UI used to promise "곧 자동 재생됩니다", but no autoplay was ever wired
    # (only togglePlay()/MediaSession call play()). Users waited for sound that never came and
    # perceived the player as broken. The honest UI invites a manual press instead.
    text = TPL.read_text(encoding="utf-8")
    assert "자동 재생" not in text


def test_play_button_reflects_actual_playback_not_play_request():
    # The button must flip to the playing state on the actual `playing` event (sound started),
    # not on `play` (play requested). HLS cold-start leaves a 3–5s gap where play() was called
    # but no audio is heard yet — the button should show a buffering state during that window.
    text = TPL.read_text(encoding="utf-8")
    # audioPlaying is driven by @playing (real start), NOT by @play (request).
    assert "@playing" in text and "audioPlaying=true" in text
    assert "@play=\"audioPlaying=true\"" not in text
    # a buffering state exists so the press→sound gap reads as "loading", not "broken".
    assert "audioBuffering" in text


def test_remount_preserves_playback_position():
    # Regression: a stall/resume during streaming triggered remountAudio(), which built a fresh
    # hls.js instance (buffering from 0) and restored currentTime via $nextTick — but that ran
    # before hls.js was seekable, so the seek was dropped and playback restarted at 0 (first
    # sentence played twice; pause→resume jumped to start). The fix hands the position into the
    # (re)attach so playback resumes in place.
    text = TPL.read_text(encoding="utf-8")
    assert "attachHls(t)" in text          # remount resumes at captured time, not a racy post-seek
    assert "startPosition" in text         # hls.js initial seek honors the resume position


def test_generate_first_is_default_with_streaming_optin():
    # 정책: VoxCPM2 는 RTF>1 라 라이브 스트리밍이 멈칫 → 생성-먼저(완성 후 mount, 끊김 없는 VOD)를
    # 기본으로 한다. 라이브 스트리밍 머신러리(lead-buffer 게이트)는 코드에 남아 opt-in(플래그 true)로만 동작.
    text = TPL.read_text(encoding="utf-8")
    assert "['streaming', 'complete', 'failed_partial'].includes(st)" not in text
    assert "const playable = (st === 'complete') && !!mp3" in text   # complete → mp3 path
    assert "audioLeadSec" in text                                    # 스트리밍 머신러리 잔존(opt-in)
    assert "audioStreamingPlayback: false" in text                  # 생성-먼저 기본(라이브 스트리밍 off)


def test_stream_poll_uses_single_timer():
    # Regression: pollStreamingManifest re-scheduled itself with no handle, so loadAudio could
    # spawn N concurrent 3s loops (the manifest request flood seen in server logs). It must be
    # guarded by a single timer that callers start/stop.
    text = TPL.read_text(encoding="utf-8")
    assert "_streamPollTimer" in text
    assert "stopStreamPoll" in text


def test_detach_audio_and_poll_hardening():
    # Codex round-2: toggling 듣기 off must fully detach (reset _audioMounted/source/timers), and
    # pollAudioJob must not wedge forever on a status error or a lost ('none') job.
    text = TPL.read_text(encoding="utf-8")
    assert "detachAudio" in text                 # clean teardown on audio-off / playable→generating
    assert "st.stage === 'none'" in text         # lost job handled, not infinite-polled
    assert "_jobPollTimer" in text               # scheduled poll is cancellable on detach


def test_highlight_uses_hls_media_timeline():
    # ffprobe measured ~0.167s/segment drift between the manifest clock (wav+pad) and the actual
    # AAC playback timeline — so highlight/seek must follow hls.js frag.start (real media time),
    # not manifest start_sec, or the highlighted sentence drifts from the audio.
    text = TPL.read_text(encoding="utf-8")
    assert "audioFragStart" in text
    assert "FRAG_BUFFERED" in text
    assert "_chunkMediaStart" in text


def test_delete_audio_ui_present():
    # 생성된 오디오 삭제 UI: 확인 후 DELETE 호출하고 상태를 초기화(재생성 가능 상태로 복귀).
    text = TPL.read_text(encoding="utf-8")
    assert "deleteAudio" in text
    assert "'/api/papers/' + name + '/audio', { method: 'DELETE' }" in text


