"""Smoke tests for the FastAPI browser application."""
from fastapi.testclient import TestClient

from execscreen.app.main import app


def test_app_renders_with_data(monkeypatch, tmp_path, mock_df):
    from execscreen.data.storage import Store

    db = tmp_path / "app.db"
    s = Store(db)
    s.insert_frame(mock_df)
    s.close()
    monkeypatch.setenv("EXECSCREEN_DB", str(db))
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "MÔ PHỎNG" in response.text
    assert "khuyến nghị đầu tư" in response.text
    assert response.text.count('id="chart-') >= 1
    assert "Forward-test giả lập" in response.text
    assert "Phương pháp &amp; giới hạn" in response.text
    with TestClient(app) as client:
        response = client.post("/", data={"action": "refresh", "capital_m": "200", "time": "10:00"})
    assert response.status_code == 200
    assert "Xếp hạng cổ phiếu" in response.text


def test_app_handles_empty_db(monkeypatch, tmp_path):
    monkeypatch.setenv("EXECSCREEN_DB", str(tmp_path / "missing.db"))
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Chưa có dữ liệu" in response.text
    assert "Tạo dữ liệu mô phỏng" in response.text
