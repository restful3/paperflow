# PaperFlow 라이브 한국어 TTS 구현 플랜 리뷰 — Codex Round 3

판정: **BLOCKING 이슈 있음.** 아직 `===PLANS_APPROVED===`를 줄 수 없습니다.

Round 2의 다른 blocking은 대부분 반영됐습니다. `const name = name` TDZ 문제는 제거됐고, Plan 2 테스트 경로는 `viewer/tests/test_audio_api.py`로 통일됐으며, `/audio/file?file=`로 manifest/audio version race도 닫는 방향으로 반영됐습니다. 하지만 사용자가 특별히 확인 요청한 sentence split 코드는 플랜 본문에 아직 sentinel 방식이 아니라 이전 구현으로 남아 있습니다.

## Blocking

1. **Plan 1 Task 1: `_split_sentences` 최종 코드가 아직 닫는 따옴표를 소비합니다.**

   위치: Plan 1 Task 1 Step 3

   현재 플랜 본문 코드:

   ```python
   _SENT_END = re.compile(r'(?<=[.!?…])[”’"\')\]】」』]?\s+')

   def _split_sentences(para):
       parts = [p.strip() for p in _SENT_END.split(para.strip()) if p.strip()]
       return parts
   ```

   이 코드는 Round 2에서 지적한 그대로입니다. optional closing quote가 split delimiter에 포함되어 소비됩니다. 따라서 테스트:

   ```python
   md = '그는 "좋다." 라고 말했다. 다음 문장.'
   assert texts == ['그는 "좋다."', "라고 말했다.", "다음 문장."]
   ```

   를 통과할 수 없습니다. 첫 조각에서 닫는 따옴표가 사라질 수 있습니다.

   사용자 메시지의 반영 내역에는 sentinel 방식으로 바꿨다고 되어 있지만, 실제 Plan 1 파일에는 아직 반영되어 있지 않습니다. 이건 즉시 테스트 실패라 blocking입니다.

   수정안:

   ```python
   _SENT_BREAK = re.compile(r'([.!?…][”’"\')\]】」』]?)\s+')

   def _split_sentences(para):
       marked = _SENT_BREAK.sub(r'\1\x00', para.strip())
       return [p.strip() for p in marked.split("\x00") if p.strip()]
   ```

   또는 문장 추출형 regex로 바꿔도 됩니다. 핵심은 종결부호와 닫는 따옴표를 delimiter로 소비하지 않는 것입니다.

## Non-blocking Nit

1. **Plan 1 상단 File Structure가 아직 `viewer/app/.../tests/test_audio_api.py`처럼 보입니다.**
   - Task 9 본문은 `viewer/tests/test_audio_api.py`로 수정됐으므로 상단 구조도 `viewer/tests/test_audio_api.py`로 맞추면 혼선이 줄어듭니다.

2. **Plan 1 Task 10 산출물 확인 glob이 versioned mp3와 맞지 않습니다.**
   - 현재 기대값이 `*_ko_audio.mp3`, `*_ko_audio.manifest.json`만 존재라고 되어 있습니다.
   - versioned publish 후에는 `*_ko_audio.<sha12>.mp3`가 맞습니다. 확인 예시는 `*_ko_audio.*.mp3`로 바꾸는 편이 정확합니다.

3. **Plan 1 Self-Review가 아직 "품질 게이트 재시도는 주석 수준"이라고 말합니다.**
   - Task 6에는 `_chunk_ok`와 1회 재시도가 실제 코드로 들어갔습니다. Self-Review 문구를 갱신하면 됩니다.

4. **`_under_audio_dir`는 방어층으로는 약합니다.**
   - 현재 설명상 `rp.parent.name == "audio"`만 보면 외부 경로의 `audio` 디렉터리도 통과할 수 있습니다. `cur.parent.resolve()`를 base로 잡고 candidate가 그 하위인지 확인하는 방식이 더 정확합니다.
   - 다만 `file` regex가 slash를 막고 `cand = cur.parent / file`로 만들기 때문에 MVP blocking은 아닙니다.

## 종합

남은 blocking은 하나입니다. Plan 1 Task 1의 `_split_sentences` 코드만 실제 sentinel 구현으로 교체하면 플랜 승인 가능 상태에 가깝습니다.

