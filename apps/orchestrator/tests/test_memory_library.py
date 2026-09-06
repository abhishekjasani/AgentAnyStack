from agent_anystack.config import Settings, get_settings
from agent_anystack.main import create_app
from fastapi.testclient import TestClient


def test_library_metadata_team_filter_and_archive(tmp_path):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=f"sqlite:///{tmp_path}/office.db"
    )
    with TestClient(app) as client:
        payload = {
            "team": "eng",
            "body": "Use a staged rollout.",
            "type": "decision",
            "projects": ["portal"],
            "tags": ["release"],
            "sensitivity": "internal",
            "pinned": True,
        }
        response = client.post(
            "/okf/facts", json=payload, headers={"X-User-Id": "alex"}
        )
        assert response.status_code == 201
        fact = response.json()
        for field in ("body", "type", "projects", "tags", "sensitivity", "pinned"):
            assert fact[field] == payload[field]
        assert fact["created_by_user"] == "alex"
        assert fact["scope"] == "team:eng"
        assert fact["created"]
        assert client.get("/okf/facts?team=design").json() == []
        assert client.get("/okf/facts?team=eng").json()[0]["id"] == fact["id"]
        assert client.delete(f"/okf/facts/{fact['id']}").status_code == 204
        assert client.get("/okf/facts?team=eng").json() == []
