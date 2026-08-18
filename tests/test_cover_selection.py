"""AI 비전 커버 선별 스테이지 테스트."""
import json
import os
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

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


def test_downscale_returns_data_url_within_bounds(tmp_path):
    p = os.path.join(str(tmp_path), "big.jpg")
    _make_img(p, 2000, 1500)
    url = mt._downscale_to_data_url(p, downscale_px=768)
    assert url.startswith("data:image/jpeg;base64,")
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
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") is None


def test_skip_when_cover_already_set(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "big.jpg"), 800, 600)
    meta = {"doc_type": "article", "cover": "hero.jpg"}
    _write_meta(d, meta)
    client = MagicMock()
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") == "hero.jpg"  # 덮어쓰지 않음


def test_skip_when_no_candidates(tmp_path):
    d = str(tmp_path)
    meta = {"doc_type": "blog"}
    _write_meta(d, meta)
    client = MagicMock()
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    client.chat.completions.create.assert_not_called()
    assert out.get("cover") is None


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


def test_parse_cover_choice_rejects_bool():
    assert mt._parse_cover_choice('{"choice": true}', 3) is None


def test_parse_cover_choice_handles_json_fence():
    assert mt._parse_cover_choice('```json\n{"choice": 2}\n```', 3) == 2


def test_parse_cover_choice_extracts_from_prose():
    assert mt._parse_cover_choice('내 선택은 다음과 같다: {"choice": 1} 입니다.', 3) == 1


def test_parse_cover_choice_out_of_range_returns_none():
    assert mt._parse_cover_choice('{"choice": 9}', 3) is None


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


def test_vision_picks_subdir_image_stores_relative_path(tmp_path):
    d = str(tmp_path)
    _make_img(os.path.join(d, "images", "fig.jpg"), 900, 700)
    meta = {"doc_type": "report"}
    _write_meta(d, meta)
    client = _mock_client_returning('{"choice": 1}')
    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)
    assert out.get("cover") == os.path.join("images", "fig.jpg")
    assert _read_cover(d) == os.path.join("images", "fig.jpg")


def test_select_cover_handles_none_metadata(tmp_path):
    out = mt.select_cover_image(str(tmp_path), None, _default_config_for_test(), client=MagicMock())
    assert out is None


def _capture_messages(monkeypatch):
    """print_warning / print_info 를 가로채 (level, text) 목록으로 모은다."""
    msgs = []
    monkeypatch.setattr(mt, "print_warning", lambda m: msgs.append(("warn", str(m))))
    monkeypatch.setattr(mt, "print_info", lambda m: msgs.append(("info", str(m))))
    return msgs


def test_api_failure_is_reported_distinctly_from_declining(tmp_path, monkeypatch):
    """모든 시도가 예외로 끝나면 '적합한 커버 없음'이 아니라 API 실패로 보고해야 한다.

    두 경우가 같은 문장으로 로깅되면, 모델이 거절한 것인지 프로바이더가
    죽은 것인지 로그만으로 구분할 수 없다(2026-08-18 진단 지연의 원인).
    """
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("429 model_cooldown")
    msgs = _capture_messages(monkeypatch)

    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)

    assert out.get("cover") is None
    texts = [t for _, t in msgs]
    assert any("Cover selection FAILED" in t for t in texts), texts
    assert not any("no suitable cover chosen" in t for t in texts), texts


def test_model_declining_still_reports_no_suitable_cover(tmp_path, monkeypatch):
    d = str(tmp_path)
    _make_img(os.path.join(d, "a.jpg"), 900, 700)
    meta = {"doc_type": "paper"}
    _write_meta(d, meta)
    client = _mock_client_returning('{"choice": null}')
    msgs = _capture_messages(monkeypatch)

    out = mt.select_cover_image(d, meta, _default_config_for_test(), client=client)

    assert out.get("cover") is None
    texts = [t for _, t in msgs]
    assert any("no suitable cover chosen" in t for t in texts), texts
    assert not any("Cover selection FAILED" in t for t in texts), texts


def _make_table_like(path, w, h):
    """표·본문처럼 회색조 잉크만 있는 이미지 — 논문에서 면적이 가장 큰 부류."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new("RGB", (w, h), (255, 255, 255))
    for y in range(10, h - 10, 12):
        for x in range(10, w - 10):
            im.putpixel((x, y), (30, 30, 30))
    im.save(path)


def _make_diagram_like(path, w, h):
    """개념도처럼 채도 높은 색면이 있는 이미지."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for i, col in enumerate([(220, 40, 40), (40, 90, 220), (30, 170, 90)]):
        x0 = 10 + i * (w // 3)
        d.rectangle([x0, h // 4, x0 + w // 4, 3 * h // 4], fill=col)
    im.save(path)


def test_gather_rescues_colorful_figure_hidden_below_the_area_cutoff(tmp_path):
    """면적만으로 뽑으면 표가 후보를 독식한다 — 색면이 있는 그림도 후보에 들어야 한다.

    2026-08-18 실측: OSWORLD 폴더는 이미지 64장인데 면적 상위 6장만 후보가 되고
    그중 3장이 완전 흑백 표였다. 개념도는 후보에 들지도 못해 비전 모델이 볼 기회가
    없었고, 결과는 '적합한 커버 없음' 이었다.
    """
    d = str(tmp_path)
    for i in range(6):                                    # 면적 최상위 6장을 표로 채운다
        _make_table_like(os.path.join(d, f"table{i}.jpg"), 1200 - i, 900)
    _make_diagram_like(os.path.join(d, "figure.jpg"), 700, 500)   # 더 작지만 그림

    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)

    assert len(out) == 6
    assert "figure.jpg" in out, out
    assert out[0] == "table0.jpg", out                     # 가장 큰 것은 여전히 1번


def test_gather_is_deterministic(tmp_path):
    d = str(tmp_path)
    for i in range(6):
        _make_table_like(os.path.join(d, f"t{i}.jpg"), 1200 - i, 900)
    _make_diagram_like(os.path.join(d, "fig.jpg"), 700, 500)
    a = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    b = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert a == b


def test_gather_work_is_bounded_far_below_area_rank_is_not_rescued(tmp_path):
    """색채 점수 계산은 면적 상위 일부만 디코딩한다(수백 장 폴더 보호).

    스캔 창 밖의 그림은 구제되지 않는다 — 의도된 비용 상한이다.
    """
    d = str(tmp_path)
    n = mt._COVER_AREA_SCAN + 5
    for i in range(n):
        _make_table_like(os.path.join(d, f"t{i:03d}.jpg"), 1200 - i, 900)
    _make_diagram_like(os.path.join(d, "zz_far.jpg"), 260, 210)   # 면적 최하위
    out = mt._gather_cover_candidates(d, min_dimension=200, max_candidates=6)
    assert "zz_far.jpg" not in out, out
