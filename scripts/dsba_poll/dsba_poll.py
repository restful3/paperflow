#!/usr/bin/env python3
"""DSBA "Agent AI" 유튜브 재생목록 → PaperFlow 자동 등록 (결정적 코어).

하이브리드 설계의 Python 절반: 폴링·diff·설명 파싱·dedup·PDF 다운로드·state·알림을
모두 결정적으로 처리한다. arXiv 링크가 없는 "제목만" 논문의 title→arXiv 해석만
인터랙티브 Claude(스킬)에게 위임한다 — 이 스크립트는 그 결과(resolved.json)를 받아
검증/등록한다. (claude -p 미사용: 과금 회피)

서브커맨드:
  seed              최초 1회. 현재 재생목록 20개 영상 + 이미 등록한 24편을 state 에 시드.
  poll              재생목록 폴링 → 신규 영상의 arXiv-링크 논문 자동 등록,
                    링크 없는 제목은 pending.json 으로 방출(해석 대기).
  resolve <file>    Claude 가 해석한 resolved.json 을 받아 검증 후 등록/보류.
  notify            마지막 알림 이후 신규 등록/보류가 있으면 council 로 Tori 에게 1회 통지.
  status            현재 state 요약.

PDF 등록 = newones/ 에 <base_arxiv_id>.pdf drop → converter watch 가 처리(= MCP submit 과 동일 경로).
"""
from __future__ import annotations
import json, os, re, sys, subprocess, tempfile, time, difflib, urllib.request, urllib.parse
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────────
PLAYLIST_ID = "PLetSlH8YjIfX06c3JZjYtn_Qaw1V_1uZY"
REPO = Path("/media/restful3/data/workspace/paperflow")
NEWONES = REPO / "newones"
OUTPUTS = REPO / "outputs"
HERE = REPO / "scripts" / "dsba_poll"
STATE = HERE / "state.json"
PENDING = HERE / "pending.json"
REVIEW = HERE / "review_queue.jsonl"
LOG = REPO / "logs" / "dsba_poll.log"

YT_DLP = os.environ.get("YT_DLP", "/home/restful3/.local/bin/yt-dlp")
COUNCIL = os.environ.get("COUNCIL", "/home/restful3/.local/bin/council")

CONFIDENCE_THRESHOLD = 0.75   # 제목해석 자동등록 최소 확신
TITLE_SIM_THRESHOLD = 0.72    # 해석된 arXiv 제목 vs 원제목 유사도 하한
MAX_RECHECK = 3               # "논문 없음" 영상 재확인 횟수(업로더가 링크 추가 가능)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
PAPER_MARKER_RE = re.compile(r"(발표\s*논문|참고\s*논문|논문\s*링크|참고\s*자료|주요\s*논문)", re.I)
# 논문 블록 안이라도 이런 줄은 논문이 아니다(블록 종료 신호)
META_PREFIX_RE = re.compile(r"^\s*(발표자|발표\s*내용|메일|주제|e-?mail|presenter|https?://)", re.I)
VENUE_RE = re.compile(r"\(\s*(NeurIPS|ICML|ICLR|ACL|EMNLP|ICAIF|AAAI|CVPR|NAACL|COLM|KDD|arXiv|ArXiv)[^)]*\)", re.I)

# ── 시드 데이터(백필로 이미 등록된 현재 재생목록) ─────────────────────────
# video_id -> 등록된 arXiv base id 목록([] = 논문 미기재 영상)
SEED_VIDEOS = {
    "KdMp9r1dn5o": ["2502.18878", "2505.20139"],
    "wgWKwinIGeA": ["2303.17651", "2403.08978"],
    "dDfTFkV_4Zc": [],
    "DGY9PrOaaPY": [],
    "eQn_4gk3_Ag": [],
    "P2TSTMGJ13o": ["2201.11903", "2203.11171"],
    "s4xnZMiEIJc": [],
    "oWBjoUVV0sE": ["2309.02427"],
    "qM5mrHnOUSI": ["2309.07864"],
    "IgFhW3Hn4bU": ["2309.07864"],
    "lPagCUo22zM": [],
    "yrMkr0ylmmU": ["2307.16789", "2310.12823"],
    "ulsBDe8I6aM": ["2307.16789", "2406.12045"],
    "Ry8q5PnFqk0": ["2508.19828", "2507.05257"],
    "nThjqg4c7nw": ["2310.08560", "2504.19413"],
    "j_ZYPpulaMc": ["2406.13381", "2502.11098"],
    "XCyB6ReRoKk": ["2503.01935", "2502.20073"],
    "veShbuEk5EQ": ["2505.16421", "2512.17102"],
    "RP_kd6t9Zn8": ["2504.20073"],
    "cnlCe0-V220": ["2508.14052", "2412.17259"],
}

def log(msg: str) -> None:
    line = f"{time.strftime('%F %T')} {msg}"
    print(line, file=sys.stderr)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass

# ── state I/O (atomic + .bak 복구) ───────────────────────────────────────
def load_state() -> dict:
    for p in (STATE, STATE.with_suffix(".json.bak")):
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                log(f"WARN state 손상: {p}")
                continue
    return {"version": 1, "videos": {}, "papers": {}, "all_video_ids": [], "notified_arxiv_ids": []}

def save_state(state: dict) -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        try:
            STATE.replace(STATE.with_suffix(".json.bak"))
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(dir=str(HERE), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)

# ── 유틸 ─────────────────────────────────────────────────────────────────
def base_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id.strip())

def norm_title(t: str) -> str:
    # 말미 괄호 인용 꼬리 제거 — 영상 제목의 "(Nature machine intelligence, 2024" 류
    # (닫는 괄호가 없어도) 꼬리가 정답 매치의 유사도를 임계 아래로 끌어내린 실측 사고 방지.
    # 중간 괄호는 보존한다.
    t = re.sub(r"\s*\([^()]*\)?\s*$", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()

def title_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()

def run_json(args: list[str]) -> dict | None:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=120)
        if out.returncode != 0 or not out.stdout.strip():
            log(f"WARN cmd 실패 rc={out.returncode}: {' '.join(args[:3])}… {out.stderr[:160]}")
            return None
        return json.loads(out.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        log(f"WARN cmd 예외: {e}")
        return None

# ── 유튜브 ────────────────────────────────────────────────────────────────
def get_playlist_entries() -> list[dict]:
    url = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"
    d = run_json([YT_DLP, "--flat-playlist", "-J", url])
    if not d:
        return []
    return [{"id": e["id"], "title": e.get("title", "")} for e in d.get("entries", []) if e.get("id")]

def get_video_description(vid: str) -> str:
    d = run_json([YT_DLP, "-J", "--skip-download", f"https://www.youtube.com/watch?v={vid}"])
    return (d or {}).get("description", "") or ""

# ── 설명 파싱 → 논문 [{title, arxiv_id|None}] ─────────────────────────────
def parse_papers(desc: str) -> list[dict]:
    """설명에서 논문 [{title, arxiv_id|None}] 추출.

    포맷 다양성: '발표 논문:' 마커 다음 줄에 불릿 없이 제목만(가장 흔함),
    '- 제목 (https://arxiv.org/abs/..)' 불릿+링크, '논문 링크: https://...' 인라인 등.
    arXiv 링크는 위치 무관 채택. 마커 블록 안의 비-메타 줄은 제목으로 채택.
    """
    papers: list[dict] = []
    seen: set[str] = set()
    in_block = False
    block_count = 0
    for ln in desc.splitlines():
        stripped = ln.strip()
        arx = ARXIV_RE.search(ln)
        if PAPER_MARKER_RE.search(ln):
            in_block, block_count = True, 0
            tail = PAPER_MARKER_RE.split(ln, maxsplit=1)[-1].strip(" :：-")
            if arx:
                _add_paper(ln, papers, seen, arx.group(1)); block_count += 1
            elif tail and len(tail) > 8 and not tail.lower().startswith("http"):
                _add_paper(tail, papers, seen, None); block_count += 1
            continue
        if not stripped:                       # 빈 줄: 논문을 이미 받았으면 블록 종료
            if block_count:
                in_block = False
            continue
        if arx:                                # 링크 있으면 위치 무관 채택
            _add_paper(ln, papers, seen, arx.group(1))
            if in_block:
                block_count += 1
            continue
        if in_block:
            if META_PREFIX_RE.match(ln):        # 메타 줄 = 블록 종료
                in_block = False
                continue
            _add_paper(ln, papers, seen, None); block_count += 1
    return papers

def _clean_title(s: str) -> str:
    s = re.sub(r"https?://\S+", "", s)         # 전체 URL 먼저(괄호 안 링크 포함)
    s = PAPER_MARKER_RE.sub("", s)
    s = ARXIV_RE.sub("", s)                     # 남은 arxiv 조각
    s = re.sub(r"^\s*[-•*]\s*", "", s)          # 선두 불릿만
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)        # 선두 번호만(연도 '2025)' 오인 방지)
    s = VENUE_RE.sub("", s)                     # (ACL 2025) 등 venue 제거
    s = re.sub(r"\(\s*\)", "", s)               # 빈 괄호 제거
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" :：-—|()[]")

def _add_paper(raw: str, papers: list, seen: set, arxiv_id: str | None = None) -> None:
    bid = base_id(arxiv_id) if arxiv_id else None
    title = _clean_title(raw)
    if not title or len(title) < 6:
        if not bid:
            return
        title = f"arXiv:{bid}"                   # 제목이 비면 id 로 대체(등록은 유지)
    key = f"id:{bid}" if bid else norm_title(title)[:60]
    if key in seen:
        return
    seen.add(key)
    papers.append({"title": title, "arxiv_id": bid})

# ── 등록(dedup + atomic download + drop) ─────────────────────────────────
def library_has_paper(bid: str, outputs: Path | None = None,
                      archives: Path | None = None) -> bool:
    """라이브러리(outputs/archives)에 이 논문 자체가 있는가.

    본문 md 전문 grep 은 쓰지 않는다 — 다른 문서의 참고문헌에 인용된 arXiv ID
    (예: ChemCrow 를 인용한 블로그 해설판)를 '보유'로 오판해 dup 처리하는
    실측 사고(2026-07-13)가 있었다. 판정 근거는 두 가지만:
    ① 폴더 내 PDF 파일명에 ID 포함  ② paper_meta.json 이 ID 를 참조.
    """
    bases = [b for b in (outputs if outputs is not None else OUTPUTS,
                         archives if archives is not None else REPO / "archives")
             if b and b.is_dir()]
    for base in bases:
        if next(base.glob(f"*/*{bid}*.pdf"), None):
            return True
        try:
            r = subprocess.run(["grep", "-rIlm1", "--include=paper_meta.json", bid, str(base)],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
    return False

def already_registered(bid: str, state: dict) -> bool:
    if bid in state["papers"]:
        return True
    if (NEWONES / f"{bid}.pdf").exists():
        return True
    return library_has_paper(bid)

def download_pdf(bid: str) -> bool:
    NEWONES.mkdir(parents=True, exist_ok=True)
    inc = NEWONES / ".incoming"
    inc.mkdir(exist_ok=True)
    part = inc / f"{bid}.pdf.part"
    url = f"https://arxiv.org/pdf/{bid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 dsba-poll"})
        with urllib.request.urlopen(req, timeout=60) as r, part.open("wb") as f:
            data = r.read()
        if not data.startswith(b"%PDF-") or len(data) < 10_000:
            log(f"WARN PDF 검증 실패 {bid} (bytes={len(data)})")
            part.unlink(missing_ok=True)
            return False
        part.write_bytes(data)
        os.replace(part, NEWONES / f"{bid}.pdf")   # atomic
        return True
    except Exception as e:                          # noqa: BLE001 (네트워크 광범위)
        log(f"WARN PDF 다운로드 실패 {bid}: {e}")
        part.unlink(missing_ok=True)
        return False

def register_paper(bid: str, title: str, vid: str, state: dict) -> str:
    bid = base_id(bid)
    if already_registered(bid, state):
        state["papers"].setdefault(bid, {"status": "registered", "title": title, "video_id": vid})
        return "dup"
    if download_pdf(bid):
        state["papers"][bid] = {"status": "dropped", "title": title, "video_id": vid,
                                "at": time.strftime("%F %T")}
        log(f"등록 {bid}  ({title[:50]})  ← {vid}")
        return "registered"
    return "download_failed"

# ── 서브커맨드 ────────────────────────────────────────────────────────────
def cmd_seed(force: bool = False) -> None:
    if STATE.exists() and not force:
        print("state.json 이미 존재 — --force 로 덮어쓰기"); return
    now = time.strftime("%F %T")
    state = {"version": 1, "videos": {}, "papers": {}, "all_video_ids": list(SEED_VIDEOS), "notified_arxiv_ids": []}
    for vid, ids in SEED_VIDEOS.items():
        state["videos"][vid] = {
            "status": "resolved" if ids else "seen_no_paper",
            "recheck_count": 0, "checked_at": now,
        }
        for bid in ids:
            state["papers"].setdefault(bid, {"status": "registered", "video_id": vid, "title": ""})
    state["notified_arxiv_ids"] = list(state["papers"])   # 시드는 알림 대상 아님
    save_state(state)
    print(f"seed 완료: 영상 {len(state['videos'])}, 논문 {len(state['papers'])}")

def cmd_poll() -> None:
    state = load_state()
    entries = get_playlist_entries()
    if not entries:
        log("poll: 재생목록 조회 실패 — 중단"); print(json.dumps({"error": "playlist fetch failed"})); return
    state["all_video_ids"] = [e["id"] for e in entries]
    pending: list[dict] = []
    registered_now: list[str] = []
    for e in entries:
        vid, vtitle = e["id"], e["title"]
        v = state["videos"].get(vid)
        if v and v["status"] == "resolved":
            continue
        if v and v["status"] == "seen_no_paper" and v.get("recheck_count", 0) >= MAX_RECHECK:
            continue
        desc = get_video_description(vid)
        papers = parse_papers(desc)
        if not papers:
            rc = (v.get("recheck_count", 0) + 1) if v else 1
            state["videos"][vid] = {"status": "seen_no_paper", "recheck_count": rc,
                                    "checked_at": time.strftime("%F %T"), "title": vtitle}
            continue
        had_pending = had_fail = had_ok = False
        for p in papers:
            if p["arxiv_id"]:
                res = register_paper(p["arxiv_id"], p["title"], vid, state)
                if res == "registered":
                    registered_now.append(p["arxiv_id"]); had_ok = True
                elif res == "download_failed":
                    had_fail = True
            else:
                pending.append({"video_id": vid, "title": p["title"], "context": vtitle})
                had_pending = True
        status = "failed_retryable" if had_fail else ("partial" if had_pending else "resolved")
        state["videos"][vid] = {"status": status, "recheck_count": 0,
                                "checked_at": time.strftime("%F %T"), "title": vtitle}
    save_state(state)
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    print(json.dumps({"registered": registered_now, "pending": pending,
                      "pending_count": len(pending)}, ensure_ascii=False, indent=2))

def cmd_resolve(path: str) -> None:
    state = load_state()
    try:
        items = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"resolved 파일 읽기 실패: {e}"); return
    registered_now, review = [], []
    for it in items:
        title, vid = it.get("title", ""), it.get("video_id", "")
        aid, conf = it.get("arxiv_id"), float(it.get("confidence", 0) or 0)
        status = it.get("status", "")
        ok = (status == "resolved" and aid and conf >= CONFIDENCE_THRESHOLD
              and _verify_arxiv(base_id(aid), title))
        if ok:
            res = register_paper(aid, title, vid, state)
            if res == "registered":
                registered_now.append(base_id(aid))
            _bump_video_resolved(state, vid)
        else:
            rec = {"title": title, "video_id": vid, "arxiv_id": aid, "confidence": conf,
                   "status": status, "ts": time.strftime("%F %T")}
            review.append(rec)
            with REVIEW.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    save_state(state)
    print(json.dumps({"registered": registered_now, "review": len(review)}, ensure_ascii=False, indent=2))

def _verify_arxiv(bid: str, title: str) -> bool:
    """등록 전 재검증: abs URL 200 + 제목 유사도(있으면)."""
    try:
        req = urllib.request.Request(f"https://arxiv.org/abs/{bid}",
                                     headers={"User-Agent": "Mozilla/5.0 dsba-poll"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read(20000).decode("utf-8", "ignore")
        if r.status != 200:
            return False
        m = re.search(r'<title>\s*(?:\[\d{4}\.\d{4,5}\]\s*)?(.*?)</title>', html, re.S)
        if m and title:
            return title_sim(m.group(1), title) >= TITLE_SIM_THRESHOLD
        return True
    except Exception:                               # noqa: BLE001
        return False

def _bump_video_resolved(state: dict, vid: str) -> None:
    v = state["videos"].get(vid)
    if v and v["status"] == "partial":
        # 이 영상의 pending 이 모두 처리됐는지는 보수적으로 partial 유지(다음 poll 이 재평가)
        v["status"] = "resolved"

def cmd_notify() -> None:
    state = load_state()
    notified = set(state.get("notified_arxiv_ids", []))
    new_papers = [(bid, p) for bid, p in state["papers"].items()
                  if bid not in notified and p.get("status") in ("dropped", "registered")]
    review_n = REVIEW.exists() and sum(1 for _ in REVIEW.open()) or 0
    if not new_papers:
        print("알림: 신규 없음"); return
    lines = [f"- {p.get('title') or '(제목미상)'} (arXiv:{bid})" for bid, p in new_papers]
    msg = ("[DSBA 자동등록] 오늘 PaperFlow 에 새 논문 "
           f"{len(new_papers)}편이 등록됐어. 사용자에게 텔레그램으로 알려줘:\n"
           + "\n".join(lines)
           + (f"\n(검토 보류 {review_n}건: scripts/dsba_poll/review_queue.jsonl)" if review_n else "")
           + "\n뷰어: https://paper.restful3.store")
    try:
        subprocess.run([COUNCIL, "send", "tori", msg], timeout=60, check=False)
        log(f"notify: Tori 통지 {len(new_papers)}편")
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"WARN notify 실패: {e}")
    state["notified_arxiv_ids"] = list(notified | {bid for bid, _ in new_papers})
    save_state(state)
    print(json.dumps({"notified": [b for b, _ in new_papers]}, ensure_ascii=False))

def cmd_status() -> None:
    state = load_state()
    vs = {}
    for v in state["videos"].values():
        vs[v["status"]] = vs.get(v["status"], 0) + 1
    print(json.dumps({"videos": vs, "papers": len(state["papers"]),
                      "notified": len(state.get("notified_arxiv_ids", []))}, ensure_ascii=False, indent=2))

def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "status"
    if cmd == "seed":
        cmd_seed(force="--force" in argv)
    elif cmd == "poll":
        cmd_poll()
    elif cmd == "resolve":
        if len(argv) < 2:
            sys.exit("usage: dsba_poll.py resolve <resolved.json>")
        cmd_resolve(argv[1])
    elif cmd == "notify":
        cmd_notify()
    elif cmd == "status":
        cmd_status()
    else:
        sys.exit(f"unknown cmd: {cmd}")

if __name__ == "__main__":
    main(sys.argv[1:])
