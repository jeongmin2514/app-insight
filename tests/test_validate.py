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

def test_retention_ref_requires_cohort():
    with pytest.raises(SchemaError, match="cohort"):
        validate_snapshot({**GOOD, "metric": "retention_ref",
                           "rows": [{"date": "2026-07-10", "first_users": 10}]})

def test_bad_date_format_fails():
    with pytest.raises(SchemaError, match="date"):
        validate_snapshot({**GOOD, "rows": [{"date": "07/10", "users": 1}]})
