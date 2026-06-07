# AI 비전 커버 선별 스테이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaperFlow 배치 파이프라인에 비전 모델 기반 커버 이미지 선별 스테이지를 추가해, 비-비디오 컨텐츠의 `paper_meta.json`에 `cover` 필드를 자동으로 채운다.

**Architecture:** `main_terminal.py`에 순수 프리필터 함수 `_gather_cover_candidates()`와 스테이지 함수 `select_cover_image()`를 추가한다. 프리필터가 PIL로 폴더 이미지를 크기·면적 기준으로 추려 상위 후보를 만들고, 비전 모델이 그중 표지 1장을 고르거나 NONE을 반환한다. `process_single_pdf`에서 중복검사 직후·번역 직전에 호출하며, optional 스테이지로서 어떤 실패도 파이프라인을 중단하지 않는다. 뷰어는 이미 `cover`를 렌더하므로 변경 없음.

**Tech Stack:** Python, Pillow(PIL, 이미 설치 10.2.0), OpenAI 호환 클라이언트(`openai` SDK), pytest 9.0.2. 테스트는 루트 `tests/`에서 `import main_terminal as mt` 패턴.

스펙: `docs/superpowers/specs/2026-06-07-ai-cover-selection-design.md`

---

## File Structure

- **Modify** `main_terminal.py`:
  - `_count_active_stages()` (line ~105) — `select_cover` 스테이지 카운트 추가
  - `default_config["processing_pipeline"]` (line ~364) + `cover_selection` 블록 추가
  - 신규 함수 `_gather_cover_candidates()` — 순수 프리필터
  - 신규 함수 `_downscale_to_data_url()` — 이미지 다운스케일 + base64 data URL
  - 신규 함수 `select_cover_image()` — 가드 + 비전 호출 + 영속화
  - `process_single_pdf()` (insert at line ~3356) — 스테이지 호출
- **Modify** `config.json` — 런타임 설정 동기화
- **Modify** `.env.example` (있으면) — `COVER_MODEL` 문서화
- **Modify** `CLAUDE.md` — 파이프라인 표/Configuration 섹션 갱신
- **Create** `tests/test_cover_selection.py` — 전체 단위 테스트

---

## Task 1: Config 기본값 + 스테이지 카운트

**Files:**
- Modify: `main_terminal.py:105-118` (`_count_active_stages`)
- Modify: `main_terminal.py:364` 부근 (`default_config`)
- Test: `tests/test_cover_selection.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cover_selection.py` 생성:

```python
"""AI 비전 커버 선별 스테이지 테스트."""
import json
import os
from unittest.mock import MagicMock

import pytest
from PIL import Image

import main_terminal as mt


def test_count_active_stages_includes_select_cover():
    pipeline = {
        "convert_to_markdown": True,
        "extract_metadata": True,
        "check_duplicate": False,
        "translate_to_korean": False,
        "select_cover": True,
    }
    # convert(1) + metadata(1) + select_cover(1) = 3
    assert mt._count_active_stages(pipeline) == 3


def test_count_active_stages_excludes_select_cover_when_off():
    pipeline = {
        "convert_to_markdown": True,
        "extract_metadata": True,
        "check_duplicate": False,
        "translate_to_korean": False,
        "select_cover": False,
    }
    assert mt._count_active_stages(pipeline) == 2


def test_default_config_has_cover_settings():
    cfg = mt.get_default_config() if hasattr(mt, "get_default_config") else None
    # 기본 config 로더가 default_config 를 반환하는 경로 사용
    # (아래 Step 3에서 실제 접근 방식에 맞게 조정)
```

> 주의: `test_default_config_has_cover_settings`는 Step 3에서 `default_config` 접근 방식을 확인한 뒤 구체화한다. 우선 `_count_active_stages` 두 테스트만 작성/실행한다. `get_default_config` 가 없으면 이 테스트는 삭제하고 config.json 검증(Task 5)으로 대체한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /media/restful3/data/workspace/paperflow && python3 -m pytest tests/test_cover_selection.py::test_count_active_stages_includes_select_cover -v`
Expected: FAIL — 현재 `_count_active_stages`는 `select_cover`를 세지 않으므로 결과가 2가 되어 `assert == 3` 실패.

- [ ] **Step 3: Implement minimal code**

`main_terminal.py`의 `_count_active_stages` (line ~105)에 `select_cover` 카운트 추가:

```python
def _count_active_stages(pipeline):
    """Count the number of active pipeline stages for progress tracking."""
    count = 0
    if pipeline.get("convert_to_markdown", True):
        count += 1
    if pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("check_duplicate", True) and pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("select_cover", True) and pipeline.get("extract_metadata", False):
        count += 1
    if pipeline.get("translate_to_korean", False):
        count += 1
    return max(count, 1)
```

그리고 `default_config["processing_pipeline"]` (line ~364)에 `select_cover` 추가 + `cover_selection` 블록을 `processing_pipeline` 바로 뒤에 추가:

```python
        "processing_pipeline": {
            "convert_to_markdown": True,
            "normalize_headings": True,
            "extract_metadata": True,
            "select_cover": True,
            "translate_to_korean": False,
        },
        "cover_selection": {
            "max_candidates": 6,
            "min_dimension": 200,
            "downscale_px": 768,
            "timeout_seconds": 60,
            "max_retries": 2,
        },
```

> `default_config` 의 정확한 위치/들여쓰기는 `sed -n '360,415p' main_terminal.py` 로 확인 후 기존 키들과 동일 스타일로 삽입한다. `enrich_with_web_search` 키가 있으면 순서를 보존하고 그 근처에 `select_cover`를 둔다.

- [ ] **Step 4: Run tests to verify pass**

Run: `python3 -m pytest tests/test_cover_selection.py -k count_active -v`
Expected: 두 테스트 PASS.

- [ ] **Step 5: Commit**

```bash
cd /media/restful3/data/workspace/paperflow
git add tests/test_cover_selection.py main_terminal.py
git commit -m "feat(pipeline): select_cover 스테이지 카운트 + config 기본값"
```

---

## Task 2: 후보 프리필터 `_gather_cover_candidates()`

폴더에서 비전에 보낼 이미지 후보를 크기·면적 기준으로 추리는 순수 함수. AI 호출 없음.

**Files:**
- Modify: `main_terminal.py` (신규 함수 추가 — `select_cover_image` 정의 바로 위)
- Test: `tests/test_cover_selection.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cover_selection.py`에 추가. 헬퍼로 실제 이미지 파일 생성:

```python
def _make_img(path, w, h, color=(120, 130, 140)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (w, h), color).save(path)


def test_gather_drops_tiny_images(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "big.jpg"), 800, 600)
    _make_img(os.path.join(d, "icon.png"), 50, 50)  # 긴 변 < 200 → 제외
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert "big.jpg" in out
    assert "icon.png" not in out


def test_gather_ranks_by_area_then_name(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "b_small.jpg"), 300, 300)   # area 90k
    _make_img(os.path.join(d, "a_large.jpg"), 800, 800)   # area 640k
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert out[0] == "a_large.jpg"  # 면적 큰 것이 먼저


def test_gather_reads_subdirs_relative_paths(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "images", "fig1.jpg"), 800, 600)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert os.path.join("images", "fig1.jpg") in out  # 폴더 상대경로


def test_gather_only_known_extensions(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "ok.jpeg"), 800, 600)
    with open(os.path.join(d, "note.txt"), "w") as f:
        f.write("x" * 5000)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert out == ["ok.jpeg"]


def test_gather_caps_at_max_candidates(tmp_path):
    d = str(tmp_path)
    for i in range(10):
        _make_img(os.path.join(d, f"img{i:02d}.jpg"), 800 - i, 600)
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert len(out) == 6


def test_gather_empty_when_no_images(tmp_path):
    out = mt._gather_cover_candidates(str(tmp_path), min_dimension=200, max_candidates=6)
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cover_selection.py -k gather -v`
Expected: FAIL — `AttributeError: module 'main_terminal' has no attribute '_gather_cover_candidates'`.

- [ ] **Step 3: Implement minimal code**

`main_terminal.py`에 추가 (`select_cover_image` 정의 바로 위):

```python
_COVER_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_COVER_SUBDIRS = ("", "images", "figures", "assets")


def _gather_cover_candidates(output_dir, min_dimension, max_candidates):
    """폴더에서 커버 후보 이미지의 폴더 상대경로 리스트를 반환.

    루트 + images/figures/assets 서브디렉토리에서 알려진 확장자 이미지를 모으고,
    긴 변이 min_dimension 미만인 것은 제외(아이콘/로고/수식조각). 면적 내림차순,
    동률은 상대경로 문자열 순으로 정렬해 상위 max_candidates개를 반환한다.
    AI 호출 없음 — 순수 함수.
    """
    from PIL import Image

    scored = []  # (-area, relpath)
    for sub in _COVER_SUBDIRS:
        dir_path = os.path.join(output_dir, sub) if sub else output_dir
        if not os.path.isdir(dir_path):
            continue
        for fname in os.listdir(dir_path):
            if not fname.lower().endswith(_COVER_IMG_EXTS):
                continue
            abs_path = os.path.join(dir_path, fname)
            if not os.path.isfile(abs_path):
                continue
            try:
                with Image.open(abs_path) as im:
                    w, h = im.size
            except Exception:
                continue
            if max(w, h) < min_dimension:
                continue
            rel = os.path.join(sub, fname) if sub else fname
            scored.append((-(w * h), rel))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [rel for _, rel in scored[:max_candidates]]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python3 -m pytest tests/test_cover_selection.py -k gather -v`
Expected: 6개 테스트 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cover_selection.py main_terminal.py
git commit -m "feat(pipeline): 커버 후보 프리필터 _gather_cover_candidates"
```

---

## Task 3: 다운스케일 헬퍼 `_downscale_to_data_url()`

비전 전송 토큰을 줄이기 위해 이미지를 다운스케일해 base64 data URL로 변환.

**Files:**
- Modify: `main_terminal.py` (신규 함수)
- Test: `tests/test_cover_selection.py`

- [ ] **Step 1: Write the failing test**

```python
def test_downscale_returns_data_url_within_bounds(tmp_path):
    p = os.path.join(str(tmp_path), "big.jpg")
    _make_img(p, 2000, 1500)
    url = mt._downscale_to_data_url(p, downscale_px=768)
    assert url.startswith("data:image/jpeg;base64,")
    # data URL 디코드 후 크기 검증
    import base64, io
    raw = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as im:
        assert max(im.size) <= 768


def test_downscale_small_image_not_upscaled(tmp_path):
    p = os.path.join(str(tmp_path), "small.jpg")
    _make_img(p, 400, 300)
    url = mt._downscale_to_data_url(p, downscale_px=768)
    import base64, io
    raw = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as im:
        assert im.size == (400, 300)  # 확대하지 않음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cover_selection.py -k downscale -v`
Expected: FAIL — `AttributeError: ... _downscale_to_data_url`.

- [ ] **Step 3: Implement minimal code**

```python
def _downscale_to_data_url(abs_path, downscale_px):
    """이미지를 긴 변 downscale_px 이하 JPEG로 줄여 base64 data URL 반환.

    원본보다 크게 확대하지 않는다. RGBA/팔레트는 RGB로 변환.
    """
    import base64
    import io
    from PIL import Image

    with Image.open(abs_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        if longest > downscale_px:
            scale = downscale_px / float(longest)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python3 -m pytest tests/test_cover_selection.py -k downscale -v`
Expected: 2개 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cover_selection.py main_terminal.py
git commit -m "feat(pipeline): 비전 전송용 이미지 다운스케일 헬퍼"
```

---

## Task 4: 스테이지 함수 `select_cover_image()` (가드 + 비전 + 영속화)

**Files:**
- Modify: `main_terminal.py` (신규 함수)
- Test: `tests/test_cover_selection.py`

함수 시그니처: `select_cover_image(output_dir, metadata, config, client=None)`. `client`는 테스트에서 mock 주입용(없으면 내부에서 OpenAI 생성). 반환값: 갱신된 `metadata` dict.

- [ ] **Step 1: Write the failing test (가드)**

```python
def _write_meta(d, meta):
    with open(os.path.join(d, "paper_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)


def _read_cover(d):
    with open(os.path.join(d, "paper_meta.json"), encoding="utf-8") as f:
        return json.load(f).get("cover")


def test_skip_when_doc_type_video(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "big.jpg"), 800, 600)
    meta = {"doc_type": "video"}
    _write_meta(d, meta)
    client = MagicMock()
    out = mt.select_cover_image(d, meta, mt._default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") is None


def test_skip_when_cover_already_set(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "big.jpg"), 800, 600)
    meta = {"doc_type": "article", "cover": "hero.jpg"}
    _write_meta(d, meta)
    client = MagicMock()
    out = mt.select_cover_image(d, meta, mt._default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") == "hero.jpg"  # 덮어쓰지 않음


def test_skip_when_no_candidates(tmp_path):
    d = str(tmp_path)
    meta = {"doc_type": "blog"}
    _write_meta(d, meta)
    client = MagicMock()
    out = mt.select_cover_image(d, meta, mt._default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") is None
```

테스트 상단에 config 헬퍼 추가:

```python
def _default_config_for_test():
    return {
        "cover_selection": {
            "max_candidates": 6,
            "min_dimension": 200,
            "downscale_px": 768,
            "timeout_seconds": 60,
            "max_retries": 2,
        }
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cover_selection.py -k "skip_when" -v`
Expected: FAIL — `AttributeError: ... select_cover_image`.

- [ ] **Step 3: Write the failing test (비전 결과 처리)**

```python
def _mock_client_returning(content):
    client = MagicMock()
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    client.chat.completions.create.return_value = resp
    return client


def test_vision_picks_index_sets_cover(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a_large.jpg"), 900, 700)  # 후보 1 (면적 최대)
    _make_img(os.path.join(d, "b_mid.jpg"), 400, 400)    # 후보 2
    meta = {"doc_type": "report"}
    _write_meta(d, meta)
    client = _mock_client_returning('{"choice": 1}')
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") == "a_large.jpg"
    assert _read_cover(d) == "a_large.jpg"  # 디스크에도 기록


def test_vision_none_leaves_cover_unset(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = _mock_client_returning('{"choice": null}')
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") is None
    assert _read_cover(d) is None


def test_vision_out_of_range_leaves_unset(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = _mock_client_returning('{"choice": 99}')
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") is None


def test_vision_bad_json_leaves_unset(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = _mock_client_returning("not json at all")
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") is None


def test_vision_exception_does_not_propagate(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("api down")
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") is None  # 예외 삼킴, cover 미설정
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cover_selection.py -k "vision" -v`
Expected: FAIL — 함수 없음.

- [ ] **Step 5: Implement `select_cover_image`**

`main_terminal.py`에 추가 (`_gather_cover_candidates`/`_downscale_to_data_url` 아래):

```python
COVER_SELECTION_PROMPT = (
    "다음은 어떤 {doc_type} 문서에서 추출한 후보 이미지들이다(1번부터 번호 매김). "
    "컨텐츠 카드의 표지(cover)로 가장 적합하고 대표성 있는 이미지 1장을 골라라. "
    "전부 수식·표·플롯·로고·인물 증명샷처럼 표지로 부적합하면 고르지 마라. "
    'JSON 으로만 답하라: {{"choice": <후보 번호 정수 또는 null>}}'
)


def select_cover_image(output_dir, metadata, config, client=None):
    """비전 모델로 커버 이미지를 선별해 metadata['cover']에 기록한다.

    optional 스테이지 — 어떤 실패도 예외를 전파하지 않고 cover 미설정으로 종료.
    가드: doc_type=='video' / cover 이미 존재 / 후보 0장 → 비전 호출 없이 스킵.
    선택 시 폴더 상대경로를 metadata['cover']에 넣고 paper_meta.json을 저장한다.
    """
    try:
        if not metadata:
            return metadata
        if metadata.get("doc_type") == "video":
            return metadata
        if metadata.get("cover"):
            return metadata

        cov = config.get("cover_selection", {})
        max_candidates = cov.get("max_candidates", 6)
        min_dimension = cov.get("min_dimension", 200)
        downscale_px = cov.get("downscale_px", 768)
        timeout = cov.get("timeout_seconds", 60)
        max_retries = cov.get("max_retries", 2)

        candidates = _gather_cover_candidates(output_dir, min_dimension, max_candidates)
        if not candidates:
            print_info("Cover selection: no candidate images, skipping")
            return metadata

        if client is None:
            api_base = os.getenv("OPENAI_BASE_URL")
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_base or not api_key:
                print_warning("Cover selection skipped: OPENAI_BASE_URL or OPENAI_API_KEY not set")
                return metadata
            from openai import OpenAI
            client = OpenAI(base_url=api_base, api_key=api_key)

        model = os.getenv("COVER_MODEL") or os.getenv("TRANSLATION_MODEL", "gemini-claude-sonnet-4-5")
        doc_type = metadata.get("doc_type") or "document"

        content = [{"type": "text",
                    "text": COVER_SELECTION_PROMPT.format(doc_type=doc_type)}]
        for idx, rel in enumerate(candidates, start=1):
            content.append({"type": "text", "text": f"후보 {idx}:"})
            data_url = _downscale_to_data_url(os.path.join(output_dir, rel), downscale_px)
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        choice = None
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0.1,
                    timeout=timeout,
                )
                raw = (resp.choices[0].message.content or "").strip()
                choice = _parse_cover_choice(raw, len(candidates))
                break
            except Exception as e:
                print_warning(f"Cover selection attempt {attempt+1} failed: {e}")

        if choice is None:
            print_info("Cover selection: no suitable cover chosen")
            return metadata

        chosen_rel = candidates[choice - 1]
        metadata["cover"] = chosen_rel
        meta_path = os.path.join(output_dir, "paper_meta.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            print_success(f"Cover selected: {chosen_rel}")
        except Exception as e:
            print_warning(f"Failed to persist cover to paper_meta.json: {e}")
        return metadata
    except Exception as e:
        print_warning(f"Cover selection error (continuing): {e}")
        return metadata


def _parse_cover_choice(raw, n_candidates):
    """비전 응답 문자열에서 1..n_candidates 정수 또는 None을 파싱.

    JSON {"choice": <int|null>} 우선, 실패 시 None. 범위 밖이면 None.
    """
    try:
        # ```json 펜스 제거
        s = raw.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:]
        data = json.loads(s)
        c = data.get("choice")
        if isinstance(c, bool):  # bool 은 int 의 서브타입 — 배제
            return None
        if isinstance(c, int) and 1 <= c <= n_candidates:
            return c
        return None
    except Exception:
        return None
```

> `_parse_cover_choice`는 위 vision 테스트들이 간접 검증한다. 별도 단위 테스트가 필요하면 Task 4에 추가해도 좋으나 필수 아님.

- [ ] **Step 6: Run all cover tests**

Run: `python3 -m pytest tests/test_cover_selection.py -v`
Expected: Task 1\~4의 모든 테스트 PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_cover_selection.py main_terminal.py
git commit -m "feat(pipeline): select_cover_image 비전 커버 선별 스테이지"
```

---

## Task 5: 파이프라인 통합 + config.json/.env/문서

**Files:**
- Modify: `main_terminal.py:3356` 부근 (`process_single_pdf` — 중복검사 직후, 번역 직전)
- Modify: `config.json`
- Modify: `.env.example` (존재 시)
- Modify: `CLAUDE.md`

- [ ] **Step 1: `process_single_pdf`에 스테이지 호출 삽입**

`main_terminal.py` line ~3356, `# Step 2: Translation` 주석 **직전**에 삽입. 이 위치에서 `output_dir`은 스마트 리네임 후 최종 경로, `metadata`는 설정됨:

```python
        # Step 1.8: Cover image selection (optional, vision)
        if pipeline.get("select_cover", True) and metadata:
            current_stage += 1
            write_processing_status(pdf_name, "selecting_cover", current_stage, total_stages, "Selecting Cover Image")
            print_info("Step 1.8: Selecting cover image with vision AI...")
            try:
                metadata = select_cover_image(output_dir, metadata, config)
                results["cover_selection"] = "done"
            except Exception as e:
                print_warning(f"Cover selection error (continuing): {e}")
                results["cover_selection"] = "error"
```

> 정확한 들여쓰기/위치는 `sed -n '3337,3362p' main_terminal.py`로 확인. duplicate-check 블록(3337\~3355)과 `# Step 2: Translation`(3357) 사이의 빈 줄(3356)에 삽입한다. `select_cover` 카운트 조건이 Task 1의 `_count_active_stages`(`select_cover` AND `extract_metadata`)와 일치하도록, 여기 `if`도 `metadata`(메타 추출 성공) 존재를 전제로 한다.

- [ ] **Step 2: 수동 통합 검증 (mock 없이 스테이지 카운트 일관성)**

`tests/test_cover_selection.py`에 통합 카운트 테스트 추가:

```python
def test_stage_count_matches_default_pipeline():
    pipeline = {
        "convert_to_markdown": True,
        "extract_metadata": True,
        "check_duplicate": True,
        "select_cover": True,
        "translate_to_korean": True,
    }
    # convert + metadata + duplicate + select_cover + translate = 5
    assert mt._count_active_stages(pipeline) == 5
```

Run: `python3 -m pytest tests/test_cover_selection.py::test_stage_count_matches_default_pipeline -v`
Expected: PASS (Task 1 구현으로 이미 통과).

- [ ] **Step 3: `config.json` 동기화**

`config.json`의 `processing_pipeline`에 `"select_cover": true` 추가, 최상위에 `cover_selection` 블록 추가:

```bash
python3 - <<'PY'
import json
p = "config.json"
c = json.load(open(p, encoding="utf-8"))
c.setdefault("processing_pipeline", {})["select_cover"] = True
c["cover_selection"] = {
    "max_candidates": 6,
    "min_dimension": 200,
    "downscale_px": 768,
    "timeout_seconds": 60,
    "max_retries": 2,
}
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("config.json updated")
PY
```

> 만약 `config.json`이 없으면(런타임 생성형) 이 스텝은 건너뛰고 `default_config`(Task 1)만으로 동작. `ls config.json`로 먼저 확인.

- [ ] **Step 4: `.env.example` 문서화 (존재 시)**

`ls .env.example` 확인 후 존재하면 추가:

```text
# Cover image selection (optional). 비우면 TRANSLATION_MODEL 사용 (비전 지원 모델 필요)
COVER_MODEL=
```

- [ ] **Step 5: `CLAUDE.md` 갱신**

`CLAUDE.md`의 Batch Pipeline 표에 커버 선별 스테이지 행을 추가하고, Configuration > config.json의 `processing_pipeline` 설명에 `select_cover`를, `.env` 목록에 `COVER_MODEL`을 추가한다. 예시(파이프라인 표 7행으로):

```markdown
| 7 | Cover Select | `select_cover_image()` | Vision: pick 표지 image from extracted figures, write `cover` to paper_meta.json (skip video/existing-cover/no-image) |
```

그리고 Configuration 섹션:

```markdown
- `processing_pipeline`: ... (convert_to_markdown, normalize_headings, extract_metadata, enrich_with_web_search, check_duplicate, select_cover, translate_to_korean)
- `cover_selection`: vision cover picker settings (max_candidates, min_dimension, downscale_px, timeout_seconds, max_retries)
```

`.env` 코드블록에 `COVER_MODEL` 한 줄 추가.

- [ ] **Step 6: 전체 테스트 재실행 + 기존 테스트 회귀 확인**

Run:
```bash
cd /media/restful3/data/workspace/paperflow
python3 -m pytest tests/ -v
```
Expected: 신규 `test_cover_selection.py` 전부 PASS, 기존 `tests/test_landing_page_guard.py` PASS (회귀 없음).

- [ ] **Step 7: Commit**

```bash
git add main_terminal.py config.json CLAUDE.md tests/test_cover_selection.py
# .env.example 이 있으면 함께 add
git commit -m "feat(pipeline): 커버 선별 스테이지 파이프라인 통합 + config/문서"
```

---

## Self-Review (작성자 체크 완료)

**Spec coverage:**
- 신규 스테이지 `select_cover_image` (스펙 §아키텍처) → Task 4
- 메타추출·리네임 직후·번역 전 호출 (§아키텍처) → Task 5 Step 1
- config 토글 + total_stages 포함 (§config 토글) → Task 1
- 가드 video/기존cover/후보0 (§조기 종료) → Task 4 (skip 테스트 3종)
- 프리필터 수집·크기·랭킹·컷오프 (§컴포넌트1) → Task 2
- 비전 선별 모델·다운스케일·프롬프트·파싱 (§컴포넌트2) → Task 3, 4
- cover 폴더 상대경로 기록 + paper_meta.json 저장 (§출력) → Task 4
- 에러처리 optional·비전 실패·예외 비전파 (§에러처리) → Task 4 (vision_exception/bad_json/none/out_of_range)
- 설정 config.json/.env (§설정) → Task 1, 5
- 테스트 전 항목 (§테스트) → Task 1\~5
- 뷰어 변경 0 (§출력) → 계획에 뷰어 변경 없음 ✓
- 백필 범위 밖 (§범위 밖) → 계획에 백필 태스크 없음 ✓

**Placeholder scan:** `get_default_config`/`_default_config_for_test` 등 미확정 접근은 해당 스텝에 "확인 후 조정" 명시. 그 외 모든 코드 스텝에 실제 코드 포함.

**Type consistency:** `_gather_cover_candidates(output_dir, min_dimension, max_candidates)`, `_downscale_to_data_url(abs_path, downscale_px)`, `select_cover_image(output_dir, metadata, config, client=None)`, `_parse_cover_choice(raw, n_candidates)` — Task 2\~5 전반에서 동일 시그니처 사용. cover 값은 폴더 상대경로(str) 일관.

> 주의: 테스트의 `_default_config_for_test()` 헬퍼와 Task 1 테스트의 `get_default_config` 참조는 서로 다른 용도다. Task 1의 `test_default_config_has_cover_settings`는 접근 방식 확인 후 구체화/삭제 대상으로 명시했으므로 충돌 아님.
