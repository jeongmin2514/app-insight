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
