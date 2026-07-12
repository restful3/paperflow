# DSBA "Agent AI" 재생목록 → PaperFlow 자동 등록

DSBA 연구실 유튜브 재생목록 [Agent AI](https://www.youtube.com/playlist?list=PLetSlH8YjIfX06c3JZjYtn_Qaw1V_1uZY)
를 **매일 1회 폴링**해, 신규 영상 설명에 소개된 논문을 arXiv로 해석·중복없이 PaperFlow에
자동 등록하고, 등록이 생기면 Tori를 통해 텔레그램으로 알린다.

## 구조 (하이브리드)

```
cron(매일 08:00 KST)
   └─ cron_nudge.sh  ──tmux send-keys──▶  paperflow:claude 윈도우 (구독 내 인터랙티브 Claude)
                                              └─ /dsba-playlist-poll 스킬 실행
                                                    1) dsba_poll.py poll      (결정적: 폴링·파싱·링크논문 등록·pending 방출)
                                                    2) WebSearch 로 제목→arXiv 해석 → resolved.json   (LLM 파트)
                                                    3) dsba_poll.py resolve   (검증·dedup·등록 / 낮은확신 보류)
                                                    4) dsba_poll.py notify     (council send tori → 텔레그램)
```

- **`claude -p` 미사용**(과금 회피). 인터랙티브 Claude 윈도우를 tmux로 구동.
- 결정적 부분은 전부 Python(`dsba_poll.py`), LLM은 "arXiv 링크 없는 제목" 해석만 담당.
- 등록 = `newones/<arxiv_id>.pdf` drop → converter watch 가 6단계 파이프라인 처리(= MCP submit 동일 경로).

## 파일

| 파일 | 역할 |
|---|---|
| `dsba_poll.py` | 결정적 코어. 서브커맨드 `seed`/`poll`/`resolve <json>`/`notify`/`status` |
| `state.json` | 상태머신. `videos{status,recheck_count}`, `papers{status}`, `notified_arxiv_ids` (atomic write + `.bak`) |
| `pending.json` | poll 이 방출한 "해석 대기" 제목 목록(스킬이 읽음) |
| `resolved.json` | 스킬이 WebSearch로 해석해 쓴 결과(resolve 가 읽음) |
| `review_queue.jsonl` | 낮은확신·미발견으로 보류된 항목(사람이 검토) |
| `cron_nudge.sh` | tmux로 claude 윈도우에 스킬 주입 |
| `~/.claude/skills/dsba-playlist-poll/SKILL.md` | LLM 워크플로 지침 |

## dedup (3층)

`state.papers` (arXiv base id) → `newones/<id>.pdf` 존재 → `outputs/` grep. arXiv 버전(`v2`)은
base id로 정규화. 재실행은 항상 안전(멱등).

## 운영

```bash
python3 scripts/dsba_poll/dsba_poll.py status      # 현재 상태 요약
python3 scripts/dsba_poll/dsba_poll.py poll        # 수동 폴링(링크논문만 자동등록)
# 수동 전체 실행은 인터랙티브 Claude 에 /dsba-playlist-poll 입력
tail -f logs/dsba_poll.log                          # 로그
```

- **일시정지**: `crontab -e` 에서 해당 줄 주석 처리.
- **재시드**(상태 초기화): `python3 scripts/dsba_poll/dsba_poll.py seed --force` (현재 20영상·24논문 기준).
- **한계**: 알림/폴링은 `paperflow:claude` 윈도우의 Claude가 살아 idle 일 때만 동작(없으면 그날 skip, 다음날 재시도). 영상 설명에 마커(`발표 논문`/`참고 논문` 등)나 arXiv 링크가 전혀 없으면 "논문 없음"으로 보고 최대 3회 재확인 후 포기.

## 첫 시드 기준(2026-06-04)

재생목록 20개 영상, 백필 등록 24편(playlist 내 중복·라이브러리 중복 제거 후). 무논문 영상 5편은
`seen_no_paper`. 시드 논문은 `notified` 처리되어 재알림하지 않음.
