from __future__ import annotations


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Scaffold is running" in response.data


def test_health_is_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "app": "Flight Tracker",
        "environment": "test",
        "database": "up",
    }
