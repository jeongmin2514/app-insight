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

## 수집 이력 메모

### 2026-07-11 (첫 수집)
- **담은 것**: dau(+new_users 확장 필드, 3앱 전기간) / retention_ref(유입경로별 주간 코호트, 신규 metric) / 인구통계는 dau의 source에 보존.
- **뺀 것과 이유**:
  - `session` — dashboard_session 응답 value가 단위 불명의 평균값(19~63 float). 콘솔 정의 확인 전까지 미수집(모르는 숫자를 차트로 만들지 않는다).
  - `conversion` — event_act_type_set으로 전환 이벤트 미설정 상태라 빈 결과. 설정 후 다음 수집부터.
  - `push` — push_template_list에 과거 발송 캠페인이 안 남아 있음(현존 그룹 1개는 발송 0건). 과거 성과(리타겟 2.08% vs 신규 0.43%)는 2026-06 콘솔에서 확인한 검증 수치로 노트에만 기록.
- **주의**: 잡플로우 retention_ref의 전체탭 first_users=2는 DAU referrer(출시 스파이크 97% 전체탭)와 어긋남 — 콘솔 코호트 산정 기준 상이 추정, 해석 주의(raw source note 참고).

### 2026-07-16
- **담은 것**: dau 3앱(7/13 이후 공백 3일 보충) / retention_ref 3앱 갱신(구름 9주차·잡플로우/데일리픽 4주차 신규 등장).
- **콘솔이 과거 날짜를 상향 정정함**: 7/13 수집분 대비 7/13 값이 구름 2→3, 잡플로우 1→4, 데일리픽 1→2로 올라옴. 지연 반영이니 재수집 시 최신 스냅샷을 믿고 upsert에 맡길 것(빌드가 fetched_at 늦은 값 채택). **당일 값은 항상 미완결**이라는 뜻이기도 함 — 수집 시각 이후 유입은 다음 수집에서 올라온다.
- **`push_template_list` 필터가 직관과 다름** (다음에 또 헤맬 부분):
  - 필터 없이 호출 → **0건**. 스마트 발송 그룹을 보려면 반드시 `isSmartMessage: true`.
  - `enabled: false` → enabled=**true**인 과거 캠페인 그룹들이 반환됨(필터가 기대대로 안 먹음).
  - `archive: true` → 0건.
  - `push_stats`의 `sentCount: 0`은 "발송 안 됨"과 "과거 통계 API 미노출"(기존 확인된 한계)을 **구분 못 함**. 발송 여부 판정 근거로 쓰지 말 것 — DAU referrer의 푸시알림 유입이 더 신뢰할 수 있는 실측 신호.
  - `push_history_list`는 **전 그룹에서 "메세지 템플릿이 없어요" 에러**. 5월에 확실히 발송한 그룹(171738, 유입 84%가 푸시)에도 동일 → 도구가 안 되는 것이지 발송 부재 신호 아님. **다시 시도하지 말 것.**
  - ⇒ 푸시 운영 상태 확정은 **콘솔 웹 UI 확인 필수**. API만으론 단정 금지.

## 매핑 주의

- 리텐션: 콘솔이 코호트 곡선을 주면 date=코호트 시작일, d1/d7/d30 %만 옮김. 없는 구간은 키 생략(날조 금지).
- 푸시: 캠페인·세그먼트 단위 그대로. ctr은 빌드가 계산하니 옮기지 않는다.
- 단위 환산·반올림 금지. 콘솔 값 그대로.
