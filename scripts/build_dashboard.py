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
    export_csv(data, Path(csv_dir))
    return dashboard


ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    build(ROOT / "data" / "raw", ROOT / "notes",
          ROOT / "data" / "dashboard.json", ROOT / "data" / "csv")
    print("OK: data/dashboard.json 생성")
