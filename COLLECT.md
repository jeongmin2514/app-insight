# 수집 가이드 (주 1~2회, 로컬 클로드 세션에서)

## 절차

1. ToolSearch로 `apps-in-toss-console` 대시보드 도구 로드 (`dashboard_dau`, `dashboard_session`,
   `dashboard_retention`, `dashboard_conversion`, `event_pageview_stats`, `push_stats`).
2. `miniapp_list`로 앱 ID 확인 후 **앱마다 따로** 조회 (계정 단위 인증 — 앱 특정 안 하면 데이터 섞임).
3. 조회 결과를 아래 envelope로 옮겨 `data/raw/{app}/{metric}-{오늘}.json` 저장.
   - app: `gureum` / `jobflow` / `dailypick`
   - 같은 날짜 재수집 OK — 빌드가 fetched_at 늦은 값으로 upsert.
   - 콘솔 응답 원본은 `source` 필드에 그대로 보존(선택이지만 권장).
4. `python scripts/build_dashboard.py` 실행 → dashboard.json/CSV 갱신 확인.
5. 관찰→해석→액션이 있으면 `notes/YYYY-MM-DD-<slug>.md` 추가 (형식은 notes/ 기존 파일 참고).
6. git commit & push → Vercel 자동 반영.

## envelope

```json
{"app": "gureum", "metric": "dau", "fetched_at": "<ISO8601 KST>",
 "range": {"start": "...", "end": "..."},
 "rows": [{"date": "YYYY-MM-DD", "users": 0}],
 "source": {}}
```

## metric별 rows 필수 필드

| metric | 필수 필드 |
|---|---|
| dau | date, users |
| session | date, sessions |
| retention | date (+선택 d1, d7, d30 — %) |
| conversion | date, rate |
| pageview | date, views |
| push | date, campaign, segment, sent, clicked |
| revenue | date, krw |

## 매핑 주의

- 리텐션: 콘솔이 코호트 곡선을 주면 date=코호트 시작일, d1/d7/d30 %만 옮김. 없는 구간은 키 생략(날조 금지).
- 푸시: 캠페인·세그먼트 단위 그대로. ctr은 빌드가 계산하니 옮기지 않는다.
- 단위 환산·반올림 금지. 콘솔 값 그대로.
