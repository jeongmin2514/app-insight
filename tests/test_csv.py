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
