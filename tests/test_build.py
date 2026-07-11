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

def test_compute_summary_weekly_windows_calendar_based():
    # 7/4~7/10 = 4+..+10 = 49, 6/27~7/3 창에는 7/1~7/3(1+2+3=6)만 존재 (결측은 0 아님·그냥 없음)
    dau = [{"date": f"2026-07-{d:02d}", "users": d, "new_users": 1} for d in range(1, 11)]
    s = compute_summary({"dau": dau})
    assert s["visits_7d"] == 49 and s["visits_prev_7d"] == 6
    assert s["new_7d"] == 7
    assert s["wow"] == round((49 - 6) / 6 * 100, 1)

def test_compute_summary_wow_none_when_no_prev():
    dau = [{"date": "2026-07-10", "users": 5, "new_users": 2}]
    s = compute_summary({"dau": dau})
    assert s["visits_prev_7d"] == 0 and s["wow"] is None

def test_compute_headline_sums_apps():
    h = compute_headline({
        "gureum": {"total_visits": 100, "last_date": "2026-07-10"},
        "jobflow": {"total_visits": 50, "last_date": "2026-07-09"},
    })
    assert h["value"] == 150 and h["as_of"] == "2026-07-10"

def test_build_includes_events_and_experiments(tmp_path):
    raw = tmp_path / "raw"; (raw / "gureum").mkdir(parents=True)
    (raw / "gureum" / "dau-2026-07-11.json").write_text(json.dumps({
        "app": "gureum", "metric": "dau", "fetched_at": "2026-07-11T00:00:00+09:00",
        "rows": [{"date": "2026-07-10", "users": 12}]}), encoding="utf-8")
    (tmp_path / "events.json").write_text(json.dumps(
        [{"app": "gureum", "date": "2026-07-10", "label": "푸시 발송"}]), encoding="utf-8")
    (tmp_path / "experiments.json").write_text(json.dumps([{
        "date": "2026-06", "title": "t", "problem": "p", "hypothesis": "h",
        "action": "a", "result": "r", "decision": "d", "status": "완료"}]), encoding="utf-8")
    d = build(raw, tmp_path / "notes", tmp_path / "dashboard.json", tmp_path / "csv",
              events_path=tmp_path / "events.json", experiments_path=tmp_path / "experiments.json")
    assert d["apps"]["gureum"]["events"] == [{"date": "2026-07-10", "label": "푸시 발송"}]
    assert d["experiments"][0]["status"] == "완료"

def test_experiments_missing_key_fails(tmp_path):
    raw = tmp_path / "raw"; (raw / "gureum").mkdir(parents=True)
    (raw / "gureum" / "dau-2026-07-11.json").write_text(json.dumps({
        "app": "gureum", "metric": "dau", "fetched_at": "2026-07-11T00:00:00+09:00",
        "rows": [{"date": "2026-07-10", "users": 12}]}), encoding="utf-8")
    (tmp_path / "experiments.json").write_text(json.dumps([{"date": "2026-06"}]), encoding="utf-8")
    with pytest.raises(SchemaError, match="experiments"):
        build(raw, tmp_path / "notes", tmp_path / "dashboard.json", tmp_path / "csv",
              experiments_path=tmp_path / "experiments.json")

def test_build_end_to_end(tmp_path):
    raw = tmp_path / "raw"; (raw / "gureum").mkdir(parents=True)
    (raw / "gureum" / "dau-2026-07-11.json").write_text(json.dumps({
        "app": "gureum", "metric": "dau", "fetched_at": "2026-07-11T00:00:00+09:00",
        "rows": [{"date": "2026-07-10", "users": 12}]}), encoding="utf-8")
    notes = tmp_path / "notes"; notes.mkdir()
    (notes / "2026-07-11-push.md").write_text(NOTE, encoding="utf-8")
    out = tmp_path / "dashboard.json"
    build(raw, notes, out, tmp_path / "csv")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["headline"]["value"] == 12
    assert saved["apps"]["gureum"]["series"]["dau"][0]["users"] == 12
    assert saved["apps"]["jobflow"]["series"] == {}  # 데이터 없는 앱도 키는 존재
    assert saved["notes"][0]["title"].startswith("리타겟")

def test_build_empty_raw_fails(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(SchemaError, match="raw"):
        build(tmp_path / "raw", tmp_path / "notes", tmp_path / "d.json", tmp_path / "csv")
