from __future__ import annotations


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"invite-only" in response.data


def test_robots_disallows_everything(client):
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert b"Disallow: /" in response.data


def test_security_headers_are_present(client):
    response = client.get("/")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_health_is_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "app": "Flight Tracker",
        "environment": "test",
        "database": "up",
    }
