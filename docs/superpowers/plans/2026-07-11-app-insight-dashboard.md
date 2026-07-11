# app-insight 미니앱 3종 그로스 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 토스 콘솔 지표를 반자동 수집해 Python으로 가공하고, 지표+인사이트 노트를 담은 공개 웹 대시보드를 Vercel에 배포한다 (취업 포트폴리오 자산).

**Architecture:** 정적 ETL — 로컬 세션에서 콘솔 MCP 조회 → `data/raw/` 스냅샷(JSON, 원본 보존·upsert 병합) → `scripts/build_dashboard.py`(pandas)가 `data/dashboard.json` + `data/csv/`(Tableau용) 생성 → `index.html`(Chart.js CDN)이 dashboard.json만 읽어 렌더 → git push → Vercel 정적 배포. 서버·DB 없음.

**Tech Stack:** Python 3 + pandas + pytest / vanilla HTML+JS + Chart.js(CDN) / git + GitHub(public) + Vercel

## Global Constraints

- 작업 루트: `C:\Users\T\Desktop\portfolio\app-insight\` (독립 git 레포. 모든 명령은 이 폴더에서 실행)
- 부모 `portfolio/` 폴더는 비공개 서류 포함 — 절대 public 레포로 만들지 않는다 (`portfolio/.gitignore`에 `app-insight/` 등록 완료)
- 실수치 전부 공개 (DAU·리텐션·푸시·수익 포함)
- 데이터 정직 원칙: 수집 누락 구간은 공백으로 표시, 보간·날조 금지. raw 스키마 이상 시 fail-loud(SchemaError로 중단, 조용히 0 채우지 않음)
- raw 원본은 수정 금지. 가공 로직 변경 시 raw에서 재빌드
- 앱 식별자 고정: `gureum`(구름한입) / `jobflow`(잡플로우) / `dailypick`(데일리픽). 콘솔 MCP는 계정 단위 인증이라 조회 시 대상 앱 특정 필수
- UI: 첫 화면 대표 숫자 1개만 크게. 한국어, `word-break: keep-all`, 모바일 대응. 프레임워크 없음(Next.js 비채택)
- 파일 인코딩 UTF-8 (PowerShell에서 파일 쓸 땐 전용 도구 사용, Out-File 금지)
- 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: raw 스냅샷 스키마 검증 (fail-loud) + 수집 가이드 COLLECT.md

**Files:**
- Create: `scripts/__init__.py` (빈 파일), `conftest.py` (빈 파일), `.gitignore`
- Create: `scripts/build_dashboard.py`
- Create: `COLLECT.md`
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces: `SchemaError(Exception)`, `validate_snapshot(snap: dict, name: str = "<snapshot>") -> None`, 상수 `APPS: dict[str,str]`, `ALLOWED_METRICS: dict[str,set]` — 이후 모든 태스크가 import
- 스냅샷 envelope(전 태스크 공통 데이터 계약):

```json
{
  "app": "gureum",
  "metric": "dau",
  "fetched_at": "2026-07-11T14:00:00+09:00",
  "range": {"start": "2026-06-11", "end": "2026-07-10"},
  "rows": [{"date": "2026-07-10", "users": 12}],
  "source": {"...MCP 응답 원본(선택)..."}
}
```

- metric별 rows 필수 필드: `dau`={date,users} / `session`={date,sessions} / `retention`={date}+선택(d1,d7,d30 — %·nullable) / `conversion`={date,rate} / `pageview`={date,views} / `push`={date,campaign,segment,sent,clicked} / `revenue`={date,krw}
- 파일 배치: `data/raw/{app}/{metric}-{수집일}.json` (예: `data/raw/gureum/dau-2026-07-11.json`)

- [ ] **Step 1: 환경 준비 + 스캐폴딩**

```
python -m pip install pandas pytest
```

`scripts/__init__.py`, `conftest.py` 를 빈 파일로 생성. `.gitignore`:

```
__pycache__/
.pytest_cache/
```

- [ ] **Step 2: 실패하는 테스트 작성** — `tests/test_validate.py`

```python
import pytest
from scripts.build_dashboard import SchemaError, validate_snapshot

GOOD = {
    "app": "gureum", "metric": "dau",
    "fetched_at": "2026-07-11T14:00:00+09:00",
    "rows": [{"date": "2026-07-10", "users": 12}],
}

def test_valid_snapshot_passes():
    validate_snapshot(GOOD)

def test_missing_envelope_key_fails():
    bad = {k: v for k, v in GOOD.items() if k != "fetched_at"}
    with pytest.raises(SchemaError, match="fetched_at"):
        validate_snapshot(bad)

def test_unknown_app_fails():
    with pytest.raises(SchemaError, match="unknown-app"):
        validate_snapshot({**GOOD, "app": "unknown-app"})

def test_unknown_metric_fails():
    with pytest.raises(SchemaError, match="mau"):
        validate_snapshot({**GOOD, "metric": "mau"})

def test_row_missing_metric_field_fails():
    with pytest.raises(SchemaError, match="users"):
        validate_snapshot({**GOOD, "rows": [{"date": "2026-07-10"}]})

def test_bad_date_format_fails():
    with pytest.raises(SchemaError, match="date"):
        validate_snapshot({**GOOD, "rows": [{"date": "07/10", "users": 1}]})
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError` 또는 `ImportError` (build_dashboard 없음)

- [ ] **Step 4: 최소 구현** — `scripts/build_dashboard.py`

```python
"""토스 콘솔 스냅샷(data/raw) → data/dashboard.json + Tableau CSV 빌드.

원칙: raw 스키마가 어긋나면 조용히 넘어가지 않고 SchemaError로 중단(fail-loud).
"""
import re

APPS = {"gureum": "구름한입", "jobflow": "잡플로우", "dailypick": "데일리픽"}
ALLOWED_METRICS = {
    "dau": {"users"},
    "session": {"sessions"},
    "retention": set(),  # d1/d7/d30은 선택·nullable
    "conversion": {"rate"},
    "pageview": {"views"},
    "push": {"campaign", "segment", "sent", "clicked"},
    "revenue": {"krw"},
}
ENVELOPE_KEYS = {"app", "metric", "fetched_at", "rows"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SchemaError(Exception):
    pass


def validate_snapshot(snap: dict, name: str = "<snapshot>") -> None:
    missing = ENVELOPE_KEYS - snap.keys()
    if missing:
        raise SchemaError(f"{name}: 필수 키 누락 {sorted(missing)}")
    if snap["app"] not in APPS:
        raise SchemaError(f"{name}: 알 수 없는 app '{snap['app']}' (허용: {sorted(APPS)})")
    metric = snap["metric"]
    if metric not in ALLOWED_METRICS:
        raise SchemaError(f"{name}: 알 수 없는 metric '{metric}' (허용: {sorted(ALLOWED_METRICS)})")
    for i, row in enumerate(snap["rows"]):
        if "date" not in row or not DATE_RE.match(str(row["date"])):
            raise SchemaError(f"{name}: rows[{i}] date 누락/형식 오류(YYYY-MM-DD): {row}")
        missing_fields = ALLOWED_METRICS[metric] - row.keys()
        if missing_fields:
            raise SchemaError(f"{name}: rows[{i}] 필드 누락 {sorted(missing_fields)}")
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_validate.py -v`
Expected: 6 passed

- [ ] **Step 6: COLLECT.md 작성** (수집 세션용 가이드 — 미래의 클로드 세션이 읽는 문서)

```markdown
# 수집 가이드 (주 1~2회, 로컬 클로드 세션에서)

## 절차
1. ToolSearch로 `apps-in-toss-console` 대시보드 도구 로드 (`dashboard_dau`, `dashboard_session`,
   `dashboard_retention`, `dashboard_conversion`, `event_pageview_stats`, `push_stats`).
2. `miniapp_list`로 앱 ID 확인 후 **앱마다 따로** 조회 (계정 단위 인증 — 앱 특정 안 하면 데이터 섞임).
3. 조회 결과를 아래 envelope로 옮겨 `data/raw/{app}/{metric}-{오늘}.json` 저장.
   - app: gureum / jobflow / dailypick
   - 같은 날짜 재수집 OK — 빌드가 fetched_at 늦은 값으로 upsert.
   - 콘솔 응답 원본은 `source` 필드에 그대로 보존(선택이지만 권장).
4. `python scripts/build_dashboard.py` 실행 → dashboard.json/CSV 갱신 확인.
5. 관찰→해석→액션이 있으면 `notes/YYYY-MM-DD-<slug>.md` 추가 (형식은 notes/ 기존 파일 참고).
6. git commit & push → Vercel 자동 반영.

## envelope
{"app":"gureum","metric":"dau","fetched_at":"<ISO8601 KST>","range":{"start":"...","end":"..."},
 "rows":[{"date":"YYYY-MM-DD","users":N}],"source":{...}}

## metric별 rows 필수 필드
dau={date,users} session={date,sessions} retention={date,(d1,d7,d30 선택·%)}
conversion={date,rate} pageview={date,views}
push={date,campaign,segment,sent,clicked} revenue={date,krw}

## 매핑 주의
- 리텐션: 콘솔이 코호트 곡선을 주면 date=코호트 시작일, d1/d7/d30 %만 옮김. 없는 구간은 키 생략(날조 금지).
- 푸시: 캠페인·세그먼트 단위 그대로. ctr은 빌드가 계산하니 옮기지 않는다.
- 단위 환산·반올림 금지. 콘솔 값 그대로.
```

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "feat: raw 스냅샷 스키마 검증(fail-loud) + 수집 가이드"
```

---

### Task 2: 스냅샷 upsert 병합 + raw 로더

**Files:**
- Modify: `scripts/build_dashboard.py` (함수 추가)
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: Task 1의 `validate_snapshot`, `SchemaError`, `ALLOWED_METRICS`
- Produces: `row_key(metric: str, row: dict)`, `merge_snapshots(snaps: list[dict]) -> list[dict]`, `load_raw(raw_dir: Path) -> dict[tuple[str,str], list[dict]]` — Task 3·4가 사용

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_merge.py`

```python
import json
import pytest
from scripts.build_dashboard import SchemaError, load_raw, merge_snapshots

def snap(fetched_at, rows, metric="dau", app="gureum"):
    return {"app": app, "metric": metric, "fetched_at": fetched_at, "rows": rows}

def test_upsert_later_fetched_wins():
    old = snap("2026-07-01T00:00:00+09:00", [{"date": "2026-06-30", "users": 5}])
    new = snap("2026-07-08T00:00:00+09:00", [{"date": "2026-06-30", "users": 7}])
    assert merge_snapshots([new, old]) == [{"date": "2026-06-30", "users": 7}]

def test_new_dates_appended_and_sorted():
    a = snap("2026-07-01T00:00:00+09:00", [{"date": "2026-06-30", "users": 5}])
    b = snap("2026-07-08T00:00:00+09:00", [{"date": "2026-06-28", "users": 3}])
    assert [r["date"] for r in merge_snapshots([a, b])] == ["2026-06-28", "2026-06-30"]

def test_push_rows_keyed_by_date_campaign_segment():
    rows = [
        {"date": "2026-07-01", "campaign": "재방문", "segment": "40대", "sent": 100, "clicked": 2},
        {"date": "2026-07-01", "campaign": "재방문", "segment": "20대", "sent": 100, "clicked": 1},
    ]
    assert len(merge_snapshots([snap("2026-07-02T00:00:00+09:00", rows, metric="push")])) == 2

def _write(dirpath, name, obj):
    (dirpath / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

def test_load_raw_groups_and_merges(tmp_path):
    g = tmp_path / "gureum"; g.mkdir()
    _write(g, "dau-2026-07-01.json", snap("2026-07-01T00:00:00+09:00", [{"date": "2026-06-30", "users": 5}]))
    _write(g, "dau-2026-07-08.json", snap("2026-07-08T00:00:00+09:00", [{"date": "2026-06-30", "users": 7}, {"date": "2026-07-07", "users": 9}]))
    data = load_raw(tmp_path)
    assert data[("gureum", "dau")] == [{"date": "2026-06-30", "users": 7}, {"date": "2026-07-07", "users": 9}]

def test_load_raw_folder_app_mismatch_fails(tmp_path):
    j = tmp_path / "jobflow"; j.mkdir()
    _write(j, "dau-2026-07-01.json", snap("2026-07-01T00:00:00+09:00", [{"date": "2026-06-30", "users": 5}], app="gureum"))
    with pytest.raises(SchemaError, match="불일치"):
        load_raw(tmp_path)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_merge.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_raw'`

- [ ] **Step 3: 구현** — `build_dashboard.py`에 추가 (파일 상단 import에 `import json`, `from pathlib import Path` 추가)

```python
def row_key(metric: str, row: dict):
    if metric == "push":
        return (row["date"], row["campaign"], row["segment"])
    return row["date"]


def merge_snapshots(snaps: list[dict]) -> list[dict]:
    """같은 키는 fetched_at이 늦은 스냅샷이 덮어씀(upsert). 재실행 안전."""
    if not snaps:
        return []
    metric = snaps[0]["metric"]
    merged = {}
    for s in sorted(snaps, key=lambda s: s["fetched_at"]):
        for row in s["rows"]:
            merged[row_key(metric, row)] = row
    return sorted(merged.values(), key=lambda r: row_key(metric, r))


def load_raw(raw_dir: Path) -> dict:
    """data/raw/{app}/{metric}-*.json 전부 로드·검증 → (app, metric)별 병합 rows."""
    groups = {}
    for path in sorted(Path(raw_dir).glob("*/*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        validate_snapshot(snap, path.name)
        if snap["app"] != path.parent.name:
            raise SchemaError(f"{path}: 폴더({path.parent.name})와 app({snap['app']}) 불일치")
        groups.setdefault((snap["app"], snap["metric"]), []).append(snap)
    return {k: merge_snapshots(v) for k, v in groups.items()}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest -v`
Expected: 11 passed (Task 1의 6개 포함)

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "feat: 스냅샷 upsert 병합 + raw 로더"
```

---

### Task 3: 인사이트 노트 파서 + 파생지표 + dashboard.json 조립

**Files:**
- Modify: `scripts/build_dashboard.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: Task 2의 `load_raw`
- Produces: `parse_note(path) -> dict`, `load_notes(notes_dir) -> list[dict]`, `with_ctr(rows) -> list[dict]`, `compute_summary(series) -> dict`, `compute_headline(summaries) -> dict`, `build(raw_dir, notes_dir, out_path, csv_dir) -> dict`, CLI `python scripts/build_dashboard.py`
- 노트 파일 형식 (`notes/YYYY-MM-DD-<slug>.md`):

```markdown
---
date: 2026-07-11
title: 리타겟 푸시가 신규 대비 5배
app: gureum
---
## 관찰
리타겟(방문자) 푸시 클릭률 2.08%, 신규획득 0.43%.
## 해석
이미 써본 유저에게 재방문 소구가 훨씬 강함.
## 액션
신규 소재 축소, 재방문 소재(일기·기록 소구) 중심으로 재편.
```

- `dashboard.json` 구조 (index.html이 읽는 유일한 계약):

```json
{
  "generated_at": "2026-07-11T15:00:00+09:00",
  "headline": {"label": "3앱 누적 방문", "value": 12345, "as_of": "2026-07-10"},
  "apps": {
    "gureum": {"name": "구름한입",
               "series": {"dau": [{"date": "...", "users": 1}], "push": [{"...": "...", "ctr": 2.08}]},
               "summary": {"dau_7d_avg": 12.3, "last_date": "2026-07-10", "total_visits": 999}}
  },
  "notes": [{"date": "...", "title": "...", "app": "...", "observe": "...", "interpret": "...", "action": "..."}]
}
```

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_build.py`

```python
import json
import pytest
from scripts.build_dashboard import (
    SchemaError, build, compute_headline, compute_summary, parse_note, with_ctr,
)

NOTE = """---
date: 2026-07-11
title: 리타겟 푸시가 신규 대비 5배
app: gureum
---
## 관찰
리타겟 2.08%, 신규 0.43%.
## 해석
재방문 소구가 강함.
## 액션
재방문 소재 중심 재편.
"""

def test_parse_note(tmp_path):
    p = tmp_path / "2026-07-11-push.md"
    p.write_text(NOTE, encoding="utf-8")
    n = parse_note(p)
    assert n["date"] == "2026-07-11" and n["app"] == "gureum"
    assert "2.08%" in n["observe"] and "재편" in n["action"]

def test_note_missing_section_fails(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text(NOTE.replace("## 액션", "## 다음"), encoding="utf-8")
    with pytest.raises(SchemaError, match="액션"):
        parse_note(p)

def test_with_ctr():
    rows = [{"date": "2026-07-01", "campaign": "c", "segment": "s", "sent": 96, "clicked": 2},
            {"date": "2026-07-01", "campaign": "c", "segment": "z", "sent": 0, "clicked": 0}]
    out = with_ctr(rows)
    assert out[0]["ctr"] == 2.08
    assert out[1]["ctr"] is None  # 0 발송은 None (0으로 날조 금지)

def test_compute_summary_last7():
    dau = [{"date": f"2026-07-{d:02d}", "users": d} for d in range(1, 11)]  # 1..10
    s = compute_summary({"dau": dau})
    assert s["dau_7d_avg"] == 7.0 and s["last_date"] == "2026-07-10" and s["total_visits"] == 55

def test_compute_headline_sums_apps():
    h = compute_headline({
        "gureum": {"total_visits": 100, "last_date": "2026-07-10"},
        "jobflow": {"total_visits": 50, "last_date": "2026-07-09"},
    })
    assert h["value"] == 150 and h["as_of"] == "2026-07-10"

def test_build_end_to_end(tmp_path):
    raw = tmp_path / "raw"; (raw / "gureum").mkdir(parents=True)
    (raw / "gureum" / "dau-2026-07-11.json").write_text(json.dumps({
        "app": "gureum", "metric": "dau", "fetched_at": "2026-07-11T00:00:00+09:00",
        "rows": [{"date": "2026-07-10", "users": 12}]}), encoding="utf-8")
    notes = tmp_path / "notes"; notes.mkdir()
    (notes / "2026-07-11-push.md").write_text(NOTE, encoding="utf-8")
    out = tmp_path / "dashboard.json"
    d = build(raw, notes, out, tmp_path / "csv")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["headline"]["value"] == 12
    assert saved["apps"]["gureum"]["series"]["dau"][0]["users"] == 12
    assert saved["apps"]["jobflow"]["series"] == {}  # 데이터 없는 앱도 키는 존재
    assert saved["notes"][0]["title"].startswith("리타겟")

def test_build_empty_raw_fails(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(SchemaError, match="raw"):
        build(tmp_path / "raw", tmp_path / "notes", tmp_path / "d.json", tmp_path / "csv")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_build.py -v`
Expected: FAIL — ImportError (parse_note 등 없음)

- [ ] **Step 3: 구현** — `build_dashboard.py`에 추가 (상단 import에 `from datetime import datetime, timedelta, timezone` 추가. `export_csv`는 Task 4에서 구현하므로 여기선 스텁으로 두지 말고 **build 안에서 호출하지 않는다** — Task 4에서 호출 추가)

```python
NOTE_SECTIONS = {"관찰": "observe", "해석": "interpret", "액션": "action"}


def parse_note(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise SchemaError(f"{Path(path).name}: front matter(---) 없음")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    for req in ("date", "title", "app"):
        if req not in meta:
            raise SchemaError(f"{Path(path).name}: front matter에 {req} 없음")
    note = {"date": meta["date"], "title": meta["title"], "app": meta["app"]}
    for kr, en in NOTE_SECTIONS.items():
        sm = re.search(rf"^## {kr}\s*\n(.*?)(?=^## |\Z)", m.group(2), re.S | re.M)
        if not sm:
            raise SchemaError(f"{Path(path).name}: '## {kr}' 섹션 없음")
        note[en] = sm.group(1).strip()
    return note


def load_notes(notes_dir: Path) -> list[dict]:
    notes_dir = Path(notes_dir)
    if not notes_dir.exists():
        return []
    return sorted((parse_note(p) for p in notes_dir.glob("*.md")),
                  key=lambda n: n["date"], reverse=True)


def with_ctr(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        r = dict(r)
        r["ctr"] = round(r["clicked"] / r["sent"] * 100, 2) if r["sent"] else None
        out.append(r)
    return out


def compute_summary(series: dict) -> dict:
    dau = series.get("dau", [])
    last7 = dau[-7:]
    return {
        "dau_7d_avg": round(sum(r["users"] for r in last7) / len(last7), 1) if last7 else None,
        "last_date": dau[-1]["date"] if dau else None,
        "total_visits": sum(r["users"] for r in dau),
    }


def compute_headline(summaries: dict) -> dict:
    dates = [s["last_date"] for s in summaries.values() if s.get("last_date")]
    return {"label": "3앱 누적 방문",
            "value": sum(s["total_visits"] for s in summaries.values()),
            "as_of": max(dates) if dates else None}


def build(raw_dir, notes_dir, out_path, csv_dir) -> dict:
    data = load_raw(Path(raw_dir))
    if not data:
        raise SchemaError(f"{raw_dir}: raw 스냅샷이 없음")
    apps = {}
    for app_id, app_name in APPS.items():
        series = {m: rows for (a, m), rows in data.items() if a == app_id}
        if "push" in series:
            series["push"] = with_ctr(series["push"])
        apps[app_id] = {"name": app_name, "series": series, "summary": compute_summary(series)}
    dashboard = {
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "headline": compute_headline({k: v["summary"] for k, v in apps.items()}),
        "apps": apps,
        "notes": load_notes(notes_dir),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=1), encoding="utf-8")
    return dashboard


ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    build(ROOT / "data" / "raw", ROOT / "notes",
          ROOT / "data" / "dashboard.json", ROOT / "data" / "csv")
    print("OK: data/dashboard.json 생성")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest -v`
Expected: 18 passed

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "feat: 노트 파서 + 파생지표 + dashboard.json 조립"
```

---

### Task 4: Tableau용 CSV export

**Files:**
- Modify: `scripts/build_dashboard.py`
- Test: `tests/test_csv.py`

**Interfaces:**
- Consumes: Task 3의 `build`, Task 2의 `load_raw`
- Produces: `export_csv(data: dict, csv_dir: Path) -> None` — `data/csv/metrics.csv`(tidy long: app,metric,date,field,value) + `data/csv/push.csv`(app,date,campaign,segment,sent,clicked,ctr). `build()`가 마지막에 호출하도록 수정

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_csv.py`

```python
import pandas as pd
from scripts.build_dashboard import export_csv

def test_metrics_csv_tidy_long(tmp_path):
    data = {("gureum", "dau"): [{"date": "2026-07-10", "users": 12}],
            ("jobflow", "retention"): [{"date": "2026-07-01", "d1": 30.5, "d7": None}]}
    export_csv(data, tmp_path)
    df = pd.read_csv(tmp_path / "metrics.csv")
    assert list(df.columns) == ["app", "metric", "date", "field", "value"]
    assert len(df) == 2  # users 1행 + d1 1행. None(d7)은 제외 — 날조 금지
    assert df[df.field == "users"].value.iloc[0] == 12

def test_push_csv_has_ctr(tmp_path):
    data = {("gureum", "push"): [
        {"date": "2026-07-01", "campaign": "재방문", "segment": "40대", "sent": 96, "clicked": 2}]}
    export_csv(data, tmp_path)
    df = pd.read_csv(tmp_path / "push.csv")
    assert df.ctr.iloc[0] == 2.08

def test_no_push_no_file(tmp_path):
    export_csv({("gureum", "dau"): [{"date": "2026-07-10", "users": 1}]}, tmp_path)
    assert not (tmp_path / "push.csv").exists()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_csv.py -v`
Expected: FAIL — ImportError (export_csv 없음)

- [ ] **Step 3: 구현** — `build_dashboard.py` 상단에 `import pandas as pd` 추가, 함수 추가, `build()`의 `return dashboard` 직전에 `export_csv(data, Path(csv_dir))` 호출 추가

```python
def export_csv(data: dict, csv_dir: Path) -> None:
    """Tableau 2차용. metrics.csv = tidy long, push.csv = 캠페인 단위 + ctr."""
    csv_dir = Path(csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    records, push_records = [], []
    for (app, metric), rows in data.items():
        if metric == "push":
            push_records += [{"app": app, **r} for r in with_ctr(rows)]
            continue
        for r in rows:
            records += [{"app": app, "metric": metric, "date": r["date"], "field": f, "value": v}
                        for f, v in r.items() if f != "date" and v is not None]
    pd.DataFrame(records, columns=["app", "metric", "date", "field", "value"]) \
        .to_csv(csv_dir / "metrics.csv", index=False, encoding="utf-8-sig")
    if push_records:
        pd.DataFrame(push_records).to_csv(csv_dir / "push.csv", index=False, encoding="utf-8-sig")
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest -v`
Expected: 21 passed

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "feat: Tableau용 CSV export (tidy long + push)"
```

---

### Task 5: 첫 실수집 — 콘솔 MCP 스냅샷 + 첫 인사이트 노트

> 이 태스크는 코드가 아니라 **데이터 수집 실행**. 콘솔 MCP 응답 스키마는 조회해봐야 알 수 있으므로, COLLECT.md 매핑 규칙에 따라 envelope로 옮긴다. 반드시 메인 세션(콘솔 MCP 인증 보유)에서 실행 — 서브에이전트 금지.

**Files:**
- Create: `data/raw/{gureum,jobflow,dailypick}/*.json` (수집 결과)
- Create: `notes/2026-07-11-push-retarget.md`
- Create: `data/dashboard.json`, `data/csv/*` (빌드 산출물)

**Interfaces:**
- Consumes: Task 1 COLLECT.md의 envelope 계약, Task 3 CLI
- Produces: index.html(Task 6)이 렌더할 실데이터 `data/dashboard.json`

- [ ] **Step 1:** ToolSearch로 콘솔 MCP 도구 로드: `select:mcp__apps-in-toss-console__miniapp_list,mcp__apps-in-toss-console__dashboard_dau,mcp__apps-in-toss-console__dashboard_session,mcp__apps-in-toss-console__dashboard_retention,mcp__apps-in-toss-console__dashboard_conversion,mcp__apps-in-toss-console__push_stats`
- [ ] **Step 2:** `miniapp_list`로 3개 앱 ID 확인. 이후 모든 조회에 앱 ID 명시 (섞임 방지)
- [ ] **Step 3:** 앱별로 DAU·세션·리텐션·전환 조회 — 기간은 도구가 허용하는 최대(가능하면 각 앱 출시일부터, 아니면 최근 30일). 구름한입은 `push_stats` 추가. 실패하는 지표(권한·미지원)는 건너뛰고 어떤 지표를 왜 못 담았는지 기록
- [ ] **Step 4:** 응답을 COLLECT.md 규칙대로 envelope JSON으로 저장 (`data/raw/{app}/{metric}-2026-07-11.json`, `source`에 원본 보존). Write 도구 사용(UTF-8)
- [ ] **Step 5:** 첫 노트 작성 — `notes/2026-07-11-push-retarget.md`: 기존 검증 수치(리타겟 푸시 2.08% vs 신규 0.43% → 재방문 소재 재편)를 Task 3의 노트 형식으로. 수치는 이미 검증된 것만
- [ ] **Step 6:** 빌드 & 검증

Run: `python scripts/build_dashboard.py`
Expected: `OK: data/dashboard.json 생성`. dashboard.json 열어 headline.value가 실제 수집 합과 일치하는지, 앱 3개 키 존재하는지 확인

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "data: 첫 수집 스냅샷 (3앱, 2026-07-11) + 첫 인사이트 노트"
```

---

### Task 6: 웹 대시보드 index.html

> **실행 규칙: 차트 코드를 쓰기 전에 반드시 `dataviz` 스킬을 로드**하고 그 색·형태 규칙을 적용한다. 아래 HTML은 구조·동작 기준선이며, 시각 디테일(팔레트·간격)은 dataviz 규칙과 실데이터 형태에 맞춰 다듬는다. 완성 후 사용자 육안 확인 필수.

**Files:**
- Create: `index.html`

**Interfaces:**
- Consumes: `data/dashboard.json` (Task 3 구조 계약 — 그 외 파일은 읽지 않음)
- Produces: Vercel이 서빙할 정적 페이지 (루트 index.html)

- [ ] **Step 1: dataviz 스킬 로드** (Skill 도구)
- [ ] **Step 2: index.html 작성** — 아래 기준선 코드 (dataviz 규칙 반영해 조정 가능)

```html
<!-- 구조 요약: 헤더(대표숫자 1개 + as_of) → 3앱 카드(스파크라인) → 앱 탭 3개(차트+지표) → 인사이트 노트 타임라인 → 푸터(GitHub 링크) -->
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>미니앱 3종 그로스 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root { --ink:#1A2B3F; --sky:#3a9cc5; --paper:#f7fafc; --line:#e2e8f0; --gold:#C99858; }
  * { box-sizing:border-box; margin:0; }
  body { font-family:Pretendard,-apple-system,'Apple SD Gothic Neo',sans-serif; background:var(--paper);
         color:var(--ink); word-break:keep-all; line-height:1.6; }
  .wrap { max-width:860px; margin:0 auto; padding:24px 16px 64px; }
  header { text-align:center; padding:32px 0 8px; }
  .eyebrow { font-size:12px; letter-spacing:.14em; color:var(--gold); font-weight:700; }
  h1 { font-size:22px; margin:6px 0 20px; }
  .headline-num { font-size:56px; font-weight:800; letter-spacing:-.02em; }
  .headline-label { color:#64748b; font-size:14px; }
  .cards { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:24px 0; }
  @media (max-width:560px){ .cards{ grid-template-columns:1fr; } }
  .card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px; }
  .card h3 { font-size:15px; } .card .sub { font-size:12px; color:#64748b; }
  .card canvas { width:100%; height:44px; margin-top:8px; }
  .tabs { display:flex; gap:6px; margin:8px 0 16px; }
  .tabs button { flex:1; padding:10px 0; border:1px solid var(--line); background:#fff; border-radius:10px;
                 font-size:14px; font-weight:600; color:#64748b; cursor:pointer; }
  .tabs button.on { background:var(--ink); color:#fff; border-color:var(--ink); }
  .panel { display:none; } .panel.on { display:block; }
  .chart-box { background:#fff; border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:12px; }
  .chart-box h4 { font-size:14px; margin-bottom:10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { padding:8px 6px; border-bottom:1px solid var(--line); text-align:right; }
  th:first-child,td:first-child { text-align:left; }
  .empty { color:#94a3b8; font-size:13px; padding:12px 0; }
  .notes h2 { font-size:18px; margin:32px 0 12px; }
  .note { background:#fff; border:1px solid var(--line); border-left:3px solid var(--gold);
          border-radius:12px; padding:14px 16px; margin-bottom:10px; }
  .note .d { font-size:12px; color:#64748b; } .note b { display:block; margin:2px 0 6px; }
  .note p { font-size:13px; } .note p span { font-weight:700; color:var(--sky); margin-right:4px; }
  footer { text-align:center; font-size:12px; color:#94a3b8; margin-top:40px; }
  footer a { color:var(--sky); }
</style>
<div class="wrap">
  <header>
    <div class="eyebrow">MINIAPP GROWTH DASHBOARD</div>
    <h1>토스 미니앱 3종 그로스 대시보드</h1>
    <div class="headline-num" id="hNum">—</div>
    <div class="headline-label" id="hLabel"></div>
  </header>
  <div class="cards" id="cards"></div>
  <div class="tabs" id="tabs"></div>
  <div id="panels"></div>
  <section class="notes"><h2>인사이트 노트 — 관찰 · 해석 · 액션</h2><div id="notes"></div></section>
  <footer>주 1~2회 반자동 수집(토스 콘솔 → Python ETL → 정적 배포) · <span id="gen"></span> 기준<br>
    <a href="https://github.com/jeongmin2514/app-insight">GitHub — 파이프라인 코드·지표 정의</a></footer>
</div>
<script>
const fmt = n => n==null ? '—' : n.toLocaleString('ko-KR');
const line = (ctx, rows, xf, yf, label) => new Chart(ctx, {
  type:'line',
  data:{ labels:rows.map(xf), datasets:[{ label, data:rows.map(yf), borderColor:'#3a9cc5',
         backgroundColor:'rgba(58,156,197,.12)', fill:true, tension:.3, pointRadius:2, spanGaps:false }]},
  options:{ plugins:{legend:{display:false}}, scales:{y:{beginAtZero:true}}, maintainAspectRatio:false }
});
fetch('data/dashboard.json').then(r=>r.json()).then(d => {
  document.getElementById('hNum').textContent = fmt(d.headline.value);
  document.getElementById('hLabel').textContent = `${d.headline.label} · ${d.headline.as_of||''} 기준`;
  document.getElementById('gen').textContent = d.generated_at.slice(0,10);
  const cards = document.getElementById('cards'), tabs = document.getElementById('tabs'),
        panels = document.getElementById('panels');
  Object.entries(d.apps).forEach(([id, app], i) => {
    const dau = app.series.dau || [];
    cards.insertAdjacentHTML('beforeend',
      `<div class="card"><h3>${app.name}</h3>
        <div class="sub">최근 7일 평균 DAU ${fmt(app.summary.dau_7d_avg)}</div>
        <canvas id="spark-${id}"></canvas></div>`);
    tabs.insertAdjacentHTML('beforeend',
      `<button data-t="${id}" class="${i===0?'on':''}">${app.name}</button>`);
    panels.insertAdjacentHTML('beforeend', `<div class="panel ${i===0?'on':''}" id="p-${id}">
      <div class="chart-box"><h4>일별 사용자 (DAU)</h4>
        ${dau.length ? `<div style="height:220px"><canvas id="dau-${id}"></canvas></div>`
                     : `<div class="empty">초기 계측 중 — 수집 시작 2026-07-11</div>`}</div>
      ${app.series.push?.length ? `<div class="chart-box"><h4>푸시 캠페인 성과</h4>
        <table><tr><th>캠페인</th><th>세그먼트</th><th>발송</th><th>클릭</th><th>클릭률</th></tr>
        ${app.series.push.map(p=>`<tr><td>${p.campaign}</td><td>${p.segment}</td>
          <td>${fmt(p.sent)}</td><td>${fmt(p.clicked)}</td><td>${p.ctr==null?'—':p.ctr+'%'}</td></tr>`).join('')}
        </table></div>` : ''}
    </div>`);
    if (dau.length) {
      line(document.getElementById(`spark-${id}`), dau.slice(-30), r=>'', r=>r.users, 'DAU')
        .options.scales = {x:{display:false}, y:{display:false}};
      line(document.getElementById(`dau-${id}`), dau, r=>r.date.slice(5), r=>r.users, 'DAU');
    }
  });
  tabs.onclick = e => { const b = e.target.closest('button'); if(!b) return;
    tabs.querySelectorAll('button').forEach(x=>x.classList.toggle('on', x===b));
    panels.querySelectorAll('.panel').forEach(p=>p.classList.toggle('on', p.id==='p-'+b.dataset.t)); };
  document.getElementById('notes').innerHTML = d.notes.map(n=>`<div class="note">
    <div class="d">${n.date} · ${d.apps[n.app]?.name||n.app}</div><b>${n.title}</b>
    <p><span>관찰</span>${n.observe}</p><p><span>해석</span>${n.interpret}</p>
    <p><span>액션</span>${n.action}</p></div>`).join('') || '<div class="empty">노트 없음</div>';
}).catch(e => { document.getElementById('hNum').textContent = '데이터 로드 실패'; console.error(e); });
</script>
```

주의: 리텐션·세션 등 추가 series가 실수집에서 확보되면 같은 `chart-box` 패턴으로 섹션 추가 (없으면 렌더 생략 — 빈 차트 금지). 스파크라인 축 숨김이 Chart.js 인스턴스 생성 후 옵션 변경으로 안 먹으면 생성 시 options에 직접 넣을 것.

- [ ] **Step 3: 로컬 서빙 + 스크린샷 확인**

```
python -m http.server 8123        # 백그라운드
npx -y playwright screenshot --viewport-size=390,844 http://localhost:8123 shot-mobile.png
npx -y playwright screenshot --viewport-size=1280,900 http://localhost:8123 shot-desktop.png
```

Expected: 대표숫자 1개 크게, 3앱 카드, 탭 전환, 노트 타임라인이 모바일·데스크탑 모두 정상. 스크린샷을 육안 확인하고 사용자에게도 보여줄 것. (스크린샷 파일은 커밋하지 않음 — `.gitignore`에 `shot-*.png` 추가)

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "feat: 웹 대시보드 index.html (대표숫자 1개 + 3앱 탭 + 노트 타임라인)"
```

---

### Task 7: GitHub public 레포 + Vercel 배포

**Files:**
- Create: `vercel.json` (선택 — 정적이라 없어도 되지만 명시)

**Interfaces:**
- Consumes: 완성된 레포 (Task 1~6)
- Produces: public GitHub repo `app-insight` + Vercel 프로덕션 URL — Task 8 README가 인용

- [ ] **Step 1:** public 공개 전 최종 점검 — 레포 안에 비공개 정보(이력서·개인정보·토큰) 없는지 `git ls-files` 전수 확인. raw 데이터·수치는 공개 승인 완료 항목
- [ ] **Step 2:** GitHub 레포 생성·푸시

```bash
gh repo create app-insight --public --source=. --push --description "토스 미니앱 3종 그로스 대시보드 — 반자동 ETL(콘솔 API→Python→정적 배포) + 인사이트 노트"
```

Expected: `https://github.com/jeongmin2514/app-insight` 생성 확인

- [ ] **Step 3:** Vercel 연결 — **사용자 액션 필요(체크포인트)**: Vercel 대시보드 → Add New Project → GitHub `app-insight` import → Framework Preset "Other", 빌드 명령 없음, Output Directory 기본. 이후 git push마다 자동 배포(스펙의 반자동 파이프라인 완성). CLI를 원하면 `npm i -g vercel` 후 사용자가 `! vercel login` → `vercel link` → `vercel --prod`
- [ ] **Step 4:** 배포 URL 접속 확인 — dashboard.json이 404 아닌지(정적 서빙 확인), 모바일 UA로도 확인
- [ ] **Step 5: 커밋** (vercel.json 만들었을 경우)

```bash
git add -A
git commit -m "chore: Vercel 배포 설정"
git push
```

---

### Task 8: README (포트폴리오 문서)

**Files:**
- Create: `README.md`
- Create: `docs/img/dashboard-mobile.png`, `docs/img/dashboard-desktop.png` (Task 6 스크린샷 재사용, 이건 커밋)

**Interfaces:**
- Consumes: Task 7의 배포 URL, Task 6 스크린샷
- Produces: 채용담당자·면접관이 읽는 레포 첫 화면

- [ ] **Step 1: README.md 작성** — 아래 구조·문장 기준(배포 URL은 Task 7 실제 값으로). 서류작성_필수기준 준수: 첫 문장은 성과/문제로 시작, 대표 숫자 절제, 셀프 후려치기 금지, em dash·가운뎃점 규칙은 서류 본문용이므로 README엔 완화하되 과장 금지

```markdown
# 토스 미니앱 3종 그로스 대시보드

직접 출시한 토스 미니앱 3종(구름한입 · 잡플로우 · 데일리픽)의 지표를
직접 정의하고, 수집 파이프라인을 만들고, 해석해서 다음 액션으로 연결하기 위해 만든 대시보드입니다.

**Live**: <배포 URL>

![dashboard](docs/img/dashboard-desktop.png)

## 아키텍처

```
[Extract]   토스 콘솔 API 조회 (주 1~2회, 반자동)
   → data/raw/{app}/{metric}-{날짜}.json   원본 보존, 날짜 키 upsert
[Transform] scripts/build_dashboard.py (Python + pandas)
   → data/dashboard.json (웹용) + data/csv/ (Tableau용)
[Serve]     index.html (Chart.js) → git push → Vercel 자동 배포
[Notes]     notes/*.md 관찰→해석→액션 → 타임라인 렌더
```

## 지표 정의

| 지표 | 정의 |
|---|---|
| DAU | 콘솔 집계 일별 사용자 수. 가공 없이 원값 |
| 누적 방문(헤드라인) | 3앱 DAU 합산. 유니크 유저가 아니므로 '방문'으로 표기 |
| 푸시 클릭률 | clicked / sent × 100, 소수 2자리. 발송 0건은 0%가 아니라 결측 처리 |
| 리텐션 d1/d7/d30 | 콘솔 코호트 원값. 미제공 구간은 공백(보간하지 않음) |

## 설계 원칙

- **정직한 데이터**: 수집 누락은 공백으로 표시. 스키마가 어긋나면 빌드가 실패한다(fail-loud).
- **서버 없음**: 반자동 스냅샷 구조에는 정적 호스팅이면 충분. 유지비 0원.
- **하나의 데이터, 두 개의 출구**: 같은 Transform 산출물이 웹(JSON)과 Tableau(CSV)를 모두 먹인다.

## 실행

pip install pandas pytest
python -m pytest                      # 지표 산식 테스트
python scripts/build_dashboard.py    # data/raw → dashboard.json + csv
python -m http.server                 # 로컬 확인

수집 절차는 [COLLECT.md](COLLECT.md) 참고.
```

- [ ] **Step 2:** 스크린샷 파일을 `docs/img/`로 복사, README 이미지 경로 확인
- [ ] **Step 3:** 커밋·푸시 & 배포 확인

```bash
git add -A
git commit -m "docs: README (아키텍처·지표 정의·설계 원칙)"
git push
```

Expected: GitHub 레포 첫 화면에서 README + 스크린샷 정상 렌더, Vercel 재배포 완료

---

## 완료 기준 (스펙 대조)

- [ ] 공개 URL에서 실데이터 대시보드 열림 (모바일 포함)
- [ ] 첫 화면 대표 숫자 1개 원칙 지켜짐
- [ ] 3앱 탭 + 인사이트 노트 타임라인 렌더
- [ ] `python -m pytest` 전체 통과 (산식·병합·fail-loud 검증)
- [ ] `data/csv/` Tableau 소스 존재 (2차 준비 완료)
- [ ] public GitHub 레포 + README, 비공개 서류 미포함 확인
- [ ] 부모 portfolio 레포에 app-insight 미추적 확인 (`git -C .. status`)

## 2차 (이번 범위 아님)

Tableau Public 대시보드 + 포트폴리오 슬라이드 신설 — 지표 누적 후 착수 (스펙 §8)
