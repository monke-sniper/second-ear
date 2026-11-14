"""The one thing that must never be broken: the server answers."""

from __future__ import annotations


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_the_app_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Second Ear" in response.text
    assert 'src="app.js"' in response.text


def test_static_assets_are_served(client):
    for path in ("/app.js", "/styles.css", "/audio-worklet.js"):
        assert client.get(path).status_code == 200, path
