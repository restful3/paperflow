"""norm_title/title_sim — 영상 제목의 말미 인용 꼬리가 유사도 검증을 깨지 않아야 한다.

실측 사고(2026-07-12): 영상 제목 끝의 "(Nature machine intelligence, 2024" 류
(닫는 괄호 없는) 인용 꼬리 때문에 정답 arXiv 제목과의 유사도가 0.716/0.718로
TITLE_SIM_THRESHOLD(0.72)에 근소 미달 → 정답 매치가 review 큐로 false rejection.

실행: python3 test_title_sim.py
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("dp", Path(__file__).parent / "dsba_poll.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

CASES_MUST_PASS = [
    # (arXiv 제목, 영상 제목) — 실측 사고 2건 + 정상 통과 1건
    ("ChemCrow: Augmenting large-language models with chemistry tools",
     "Augmenting Large Language Models with Chemistry tools (Nature machine intelligence, 2024"),
    ("Agent Laboratory: Using LLM Agents as Research Assistants",
     "Agent Laboratory: Using LLM Agents as Research Assistants (Schmidgall, Samuel, et al. EMNLP 2025 Findings"),
    ("The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery",
     "The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery (Lu, Chris, et al. arXiv 2024"),
]

CASES_MUST_FAIL = [
    # 다른 논문은 여전히 걸러져야 한다 (임계 완화가 아니라 꼬리 제거임을 확인)
    ("Reflexion: Language Agents with Verbal Reinforcement Learning",
     "Agent Laboratory: Using LLM Agents as Research Assistants (Schmidgall, Samuel, et al. EMNLP 2025 Findings"),
]

def main():
    failures = []
    for arxiv, video in CASES_MUST_PASS:
        sim = dp.title_sim(arxiv, video)
        ok = sim >= dp.TITLE_SIM_THRESHOLD
        print(f"{'PASS' if ok else 'FAIL'} sim={sim:.3f} (>= {dp.TITLE_SIM_THRESHOLD}) : {video[:60]}")
        if not ok:
            failures.append(video)
    for arxiv, video in CASES_MUST_FAIL:
        sim = dp.title_sim(arxiv, video)
        ok = sim < dp.TITLE_SIM_THRESHOLD
        print(f"{'PASS' if ok else 'FAIL'} sim={sim:.3f} (<  {dp.TITLE_SIM_THRESHOLD}) : [다른 논문] {video[:40]}")
        if not ok:
            failures.append("negative:" + video)
    # 중간 괄호는 보존되는지 (꼬리만 제거)
    mid = dp.norm_title("Retrieval-Augmented Generation (RAG) for Knowledge Tasks")
    ok = "rag" in mid
    print(f"{'PASS' if ok else 'FAIL'} 중간 괄호 보존: {mid!r}")
    if not ok:
        failures.append("mid-paren")
    failures += test_library_has_paper()
    if failures:
        raise SystemExit(f"\n{len(failures)} case(s) failed")
    print("\nall green")


# ---------------------------------------------------------------------------
# library_has_paper — 다른 문서의 "인용"을 라이브러리 보유로 오판하면 안 된다.
# 실측 사고(2026-07-13): outputs 전문 grep이 참고문헌 속 arXiv ID(ChemCrow를
# 인용한 블로그 해설판)를 매치 → dup 처리 → PDF 미다운로드인데 state=registered.
def test_library_has_paper():
    import tempfile, os
    from pathlib import Path
    failures = []
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "outputs"; arc = Path(td) / "archives"
        # A: 본문에서 인용만 함 → 보유 아님
        a = out / "Some Blog Explainer"; a.mkdir(parents=True)
        (a / "post.md").write_text("as shown in ChemCrow (arXiv:2304.05376) ...")
        # B: paper_meta.json 에 소스 참조 → 보유
        b = out / "Agent Laboratory"; b.mkdir()
        (b / "paper_meta.json").write_text('{"url": "https://arxiv.org/abs/2501.04227"}')
        # C: PDF 파일명 매치 (archives) → 보유
        c = arc / "AI Scientist"; c.mkdir(parents=True)
        (c / "2408.06292.pdf").write_text("pdf")
        cases = [("2304.05376", False, "인용만 → 미보유"),
                 ("2501.04227", True,  "paper_meta.json → 보유"),
                 ("2408.06292", True,  "archives PDF 파일명 → 보유")]
        for bid, want, label in cases:
            got = dp.library_has_paper(bid, outputs=out, archives=arc)
            ok = got == want
            print(f"{'PASS' if ok else 'FAIL'} library_has_paper({bid})={got} (want {want}) : {label}")
            if not ok:
                failures.append(bid)
    return failures

if __name__ == "__main__":
    main()
