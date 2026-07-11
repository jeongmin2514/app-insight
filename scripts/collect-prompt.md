# app-insight 일일 자동 수집 (무인 실행용 지시서)

너는 매일 아침 자동 실행되는 수집 태스크다. 사람이 지켜보지 않는다. 아래를 순서대로 수행하라.

## 절차

1. 토스 콘솔 MCP로 3개 앱의 DAU를 **최근 7일 범위**(오늘 포함)로 조회한다.
   - workspaceId `39557` / 구름한입 `31999` / 잡플로우 `39989` / 데일리픽 `40567`
   - 도구: `mcp__apps-in-toss-console__dashboard_dau` (timeUnit DAY)
2. 응답의 au/newAu를 envelope 형식으로 저장:
   `C:\Users\T\Desktop\portfolio\app-insight\data\raw\{app}\dau-{오늘날짜}.json`
   - app 폴더명: gureum / jobflow / dailypick
   - 형식은 기존 파일(`dau-2026-07-11b.json`) 참고: `{"app","metric":"dau","fetched_at","range","rows":[{"date","users","new_users"}],"source":{"note"}}`
   - 콘솔 응답에 없는 날짜는 절대 0으로 만들지 말 것 (결측 유지). 당일 부분 집계는 그대로 저장 (다음날 upsert로 확정됨).
3. 일요일이면 리텐션도 갱신: `dashboard_retention`(dimension REFERRER, timeUnit WEEK, 출시일~오늘)을 3앱 조회해
   `retention_ref-{오늘}.json`으로 저장 (기존 파일 형식 참고, isCompletedData=true 구간만).
4. 빌드·검증·배포:
   ```
   cd C:\Users\T\Desktop\portfolio\app-insight
   python -m pytest        # 실패 시 여기서 중단
   python scripts/build_dashboard.py
   git add -A
   git commit -m "data: 자동 수집 {오늘날짜}"
   git push
   ```
5. 성공하면 아무 알림 없이 종료.

## 실패 시 (MCP 인증 만료 · 조회 에러 · 테스트 실패)

- **아무것도 커밋·푸시하지 말고**, PowerShell로 토스트 알림을 띄운 뒤 종료:
  ```powershell
  powershell -c "New-BurntToastNotification -Text 'app-insight 수집 실패','claude에서 /mcp 재인증 필요' " 2>$null || msg %USERNAME% "app-insight 수집 실패 - claude /mcp 재인증 필요"
  ```
- 실패 원인 한 줄을 `C:\Users\T\Desktop\portfolio\app-insight\collect.log`에 남겨라.

## 금지

- 인사이트 노트·실험·이벤트 파일을 새로 만들지 말 것 (그건 사람이 쓴다).
- 스키마 확장·코드 수정 금지. 수집과 빌드만.
