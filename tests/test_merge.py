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
