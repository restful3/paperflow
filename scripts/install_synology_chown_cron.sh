#!/usr/bin/env bash
# Synology Drive ↔ Docker 권한 충돌 방지용 root 크론 설치.
#
# 배경: converter/tts 컨테이너는 /root/.cache(CUDA 모델 캐시) 때문에 root 로 실행되고,
# 그 결과 ./outputs ./logs ./newones ./archives 에 root 소유 파일/폴더를 만든다.
# Synology Drive 데몬은 사용자 restful3 로 돌기 때문에 root 소유 디렉터리로
# 파일을 rename/다운로드하지 못해 "(-3) System error" 무한 재시도(동기화 정체)가 난다.
# 이 크론이 10분마다 소유권을 restful3 로 되돌려 동기화가 막히지 않게 한다.
#
# chown 은 ctime 만 바꾸고 mtime 은 건드리지 않으므로 폴더가 "오늘"로 재정렬되거나
# Synology 가 재업로드하는 부작용은 없다.
#
# 사용법:  sudo bash scripts/install_synology_chown_cron.sh
set -euo pipefail

TARGET="/media/restful3/data/workspace/paperflow"
OWNER="restful3:restful3"
LINE="*/10 * * * * chown -R $OWNER $TARGET"

if [ "$(id -u)" -ne 0 ]; then
  echo "이 스크립트는 root 크론을 수정합니다. 다음처럼 실행하세요:" >&2
  echo "  sudo bash $0" >&2
  exit 1
fi

# 즉시 한 번 적용
chown -R "$OWNER" "$TARGET"
echo "[1/2] 즉시 chown 적용 완료: $TARGET"

# idempotent: 기존 동일 라인 제거 후 재추가 (여러 번 실행해도 한 줄만 유지)
( crontab -l 2>/dev/null | grep -vF "chown -R $OWNER $TARGET" ; echo "$LINE" ) | crontab -
echo "[2/2] root 크론 등록 완료. 현재 등록 내용:"
crontab -l | grep -F "$TARGET"
