"""토스 콘솔 스냅샷(data/raw) → data/dashboard.json + Tableau CSV 빌드.

원칙: raw 스키마가 어긋나면 조용히 넘어가지 않고 SchemaError로 중단(fail-loud).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

APPS = {"gureum": "구름한입", "jobflow": "잡플로우", "dailypick": "데일리픽"}
ALLOWED_METRICS = {
    "dau": {"users"},
    "session": {"sessions"},
    "retention": set(),  # d1/d7/d30은 선택·nullable
    "retention_ref": {"cohort", "first_users"},  # 유입경로별 코호트, w1..wN은 선택(비율 원값)
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


def row_key(metric: str, row: dict):
    if metric == "push":
        return (row["date"], row["campaign"], row["segment"])
    if metric == "retention_ref":
        return (row["date"], row["cohort"])
    return row["date"]


def merge_snapshots(snaps: list) -> list:
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


def load_notes(notes_dir: Path) -> list:
    notes_dir = Path(notes_dir)
    if not notes_dir.exists():
        return []
    return sorted((parse_note(p) for p in notes_dir.glob("*.md")),
                  key=lambda n: n["date"], reverse=True)


def with_ctr(rows: list) -> list:
    out = []
    for r in rows:
        r = dict(r)
        r["ctr"] = round(r["clicked"] / r["sent"] * 100, 2) if r["sent"] else None
        out.append(r)
    return out


def _window_sum(rows: list, end: "datetime.date", days: int, field: str) -> int:
    """end 포함 최근 days일(달력 기준) 합. 결측일은 0으로 채우지 않고 그냥 없음."""
    from datetime import date, timedelta
    start = end - timedelta(days=days - 1)
    total = 0
    for r in rows:
        d = date.fromisoformat(r["date"])
        if start <= d <= end:
            total += r.get(field) or 0
    return total


def compute_summary(series: dict) -> dict:
    from datetime import date, timedelta
    dau = series.get("dau", [])
    if not dau:
        return {"dau_7d_avg": None, "last_date": None, "total_visits": 0,
                "visits_7d": 0, "visits_prev_7d": 0, "new_7d": 0, "new_prev_7d": 0, "wow": None}
    end = date.fromisoformat(dau[-1]["date"])
    prev_end = end - timedelta(days=7)
    v7 = _window_sum(dau, end, 7, "users")
    p7 = _window_sum(dau, prev_end, 7, "users")
    return {
        "dau_7d_avg": round(v7 / 7, 1),
        "last_date": dau[-1]["date"],
        "total_visits": sum(r["users"] for r in dau),
        "visits_7d": v7,
        "visits_prev_7d": p7,
        "new_7d": _window_sum(dau, end, 7, "new_users"),
        "new_prev_7d": _window_sum(dau, prev_end, 7, "new_users"),
        "wow": round((v7 - p7) / p7 * 100, 1) if p7 else None,
    }


EXPERIMENT_KEYS = {"date", "title", "problem", "hypothesis", "action", "result", "decision", "status"}


def load_experiments(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    for i, x in enumerate(items):
        missing = EXPERIMENT_KEYS - x.keys()
        if missing:
            raise SchemaError(f"experiments.json[{i}]: 필수 키 누락 {sorted(missing)}")
    return items


def load_events(path) -> dict:
    """data/events.json → app별 [{date,label}] (수기 운영 로그)."""
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    for i, e in enumerate(json.loads(path.read_text(encoding="utf-8"))):
        missing = {"app", "date", "label"} - e.keys()
        if missing:
            raise SchemaError(f"events.json[{i}]: 필수 키 누락 {sorted(missing)}")
        out.setdefault(e["app"], []).append({k: v for k, v in e.items() if k != "app"})
    return out


def compute_headline(summaries: dict) -> dict:
    dates = [s["last_date"] for s in summaries.values() if s.get("last_date")]
    v7 = sum(s.get("visits_7d", 0) for s in summaries.values())
    p7 = sum(s.get("visits_prev_7d", 0) for s in summaries.values())
    n7 = sum(s.get("new_7d", 0) for s in summaries.values())
    np7 = sum(s.get("new_prev_7d", 0) for s in summaries.values())
    return {"label": "3앱 누적 방문",
            "value": sum(s["total_visits"] for s in summaries.values()),
            "as_of": max(dates) if dates else None,
            "visits_7d": v7, "visits_prev_7d": p7,
            "wow": round((v7 - p7) / p7 * 100, 1) if p7 else None,
            "new_7d": n7, "new_prev_7d": np7,
            "new_wow": round((n7 - np7) / np7 * 100, 1) if np7 else None}


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


def build(raw_dir, notes_dir, out_path, csv_dir, events_path=None, experiments_path=None) -> dict:
    data = load_raw(Path(raw_dir))
    if not data:
        raise SchemaError(f"{raw_dir}: raw 스냅샷이 없음")
    events = load_events(events_path) if events_path else {}
    apps = {}
    for app_id, app_name in APPS.items():
        series = {m: rows for (a, m), rows in data.items() if a == app_id}
        if "push" in series:
            series["push"] = with_ctr(series["push"])
        apps[app_id] = {"name": app_name, "series": series,
                        "summary": compute_summary(series),
                        "events": events.get(app_id, [])}
    dashboard = {
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "headline": compute_headline({k: v["summary"] for k, v in apps.items()}),
        "apps": apps,
        "notes": load_notes(notes_dir),
        "experiments": load_experiments(experiments_path) if experiments_path else [],
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=1), encoding="utf-8")
    export_csv(data, Path(csv_dir))
    return dashboard


ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    build(ROOT / "data" / "raw", ROOT / "notes",
          ROOT / "data" / "dashboard.json", ROOT / "data" / "csv",
          events_path=ROOT / "data" / "events.json",
          experiments_path=ROOT / "data" / "experiments.json")
    print("OK: data/dashboard.json 생성")
