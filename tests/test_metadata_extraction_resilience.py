"""메타데이터 추출 실패가 조용히 넘어가지 않도록 하는 회귀 테스트.

실측 결함(logs/paperflow_2026*.log, 16건):
    ⚠ Metadata extraction API error: 'NoneType' object has no attribute 'strip'
gpt-5.5 류 추론 모델이 content=None(추론 토큰으로 예산 소진, finish_reason='length')을
반환하면 `.strip()` 이 AttributeError 를 던졌고, 그 결과 paper_meta.json 이 없는 채로
파이프라인이 계속 진행돼 뷰어 목록에 제목·요약·썸네일이 전부 빈 카드가 남았다.
"""
import json
import os
import types

import main_terminal as mt


def _resp(content, finish_reason="stop"):
    """OpenAI chat.completions 응답 최소 스텁."""
    msg = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=msg, finish_reason=finish_reason)
    return types.SimpleNamespace(choices=[choice])


_GOOD = json.dumps({
    "title": "A Real Title", "title_ko": "진짜 제목",
    "authors": ["A"], "abstract": "x", "abstract_ko": "엑스",
    "categories": ["C"], "source_language": "en",
    "publication_year": 2026, "doc_type": "paper",
})


def _setup(tmp_path, monkeypatch, responses):
    """md 파일 하나를 만들고 OpenAI 클라이언트를 응답 시퀀스로 대체한다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://stub/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "stub")
    monkeypatch.setenv("TRANSLATION_MODEL", "stub-model")
    out = tmp_path / "outputs" / "doc"
    out.mkdir(parents=True)
    md = out / "doc.md"
    md.write_text("# Doc\n\nSome body text long enough to send.\n", encoding="utf-8")

    calls = []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            r = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(r, Exception):
                raise r
            return r

    class _Client:
        def __init__(self, *a, **k):
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setattr(mt, "OpenAI", _Client, raising=False)
    import openai
    monkeypatch.setattr(openai, "OpenAI", _Client)
    return str(md), str(out), calls


def test_none_content_does_not_raise_attributeerror(tmp_path, monkeypatch):
    """content=None 이어도 AttributeError 로 죽지 않고 재시도 후 정상 결과를 낸다."""
    md, out, calls = _setup(tmp_path, monkeypatch,
                            [_resp(None, "length"), _resp(_GOOD)])
    meta = mt.extract_paper_metadata(md, out, mt.load_config())
    assert meta is not None, "content=None 이후 재시도로 복구되어야 한다"
    assert meta["title"] == "A Real Title"
    assert os.path.exists(os.path.join(out, "paper_meta.json"))


def test_length_truncation_retries_with_larger_budget(tmp_path, monkeypatch):
    """finish_reason='length' 면 다음 시도는 더 큰 max_tokens 로 올려서 재요청한다."""
    md, out, calls = _setup(tmp_path, monkeypatch,
                            [_resp(None, "length"), _resp(_GOOD)])
    mt.extract_paper_metadata(md, out, mt.load_config())
    assert len(calls) >= 2
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"], (
        "length 로 잘렸으면 토큰 예산을 늘려 재시도해야 한다")


def test_persistent_failure_writes_failure_marker(tmp_path, monkeypatch):
    """모든 재시도가 실패하면 디스크에 실패 마커를 남겨 나중에 찾을 수 있어야 한다."""
    md, out, _ = _setup(tmp_path, monkeypatch, [_resp(None, "length")])
    meta = mt.extract_paper_metadata(md, out, mt.load_config())
    assert meta is None
    marker = os.path.join(out, "paper_meta.failed.json")
    assert os.path.exists(marker), "영구 실패는 조용히 사라지면 안 된다"
    rec = json.loads(open(marker, encoding="utf-8").read())
    assert rec.get("stage") == "extract_metadata"
    assert rec.get("reason")


def test_success_clears_stale_failure_marker(tmp_path, monkeypatch):
    """재처리로 성공하면 이전 실패 마커는 지워져야 한다."""
    md, out, _ = _setup(tmp_path, monkeypatch, [_resp(_GOOD)])
    marker = os.path.join(out, "paper_meta.failed.json")
    with open(marker, "w", encoding="utf-8") as f:
        json.dump({"stage": "extract_metadata", "reason": "old"}, f)
    assert mt.extract_paper_metadata(md, out, mt.load_config()) is not None
    assert not os.path.exists(marker)
