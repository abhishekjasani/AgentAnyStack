from agent_anystack.config import Settings, get_settings
from agent_anystack.main import create_app
from fastapi.testclient import TestClient


def test_directory_persistence_validation_and_session_identity(tmp_path):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=f"sqlite:///{tmp_path}/office.db"
    )
    with TestClient(app) as client:
        initial = client.get("/office/people").json()
        assert initial[0]["is_current"] is True
        assert initial[0]["registered"] is False
        body = {"id": "alex", "name": "Alex", "team": "design", "title": "Designer"}
        assert client.post("/office/people", json=body).status_code == 201
        assert client.post("/office/people", json=body).status_code == 409
        assert (
            client.post("/office/people", json={**body, "id": "../bad"}).status_code
            == 422
        )
        assert (
            client.post("/office/people", json={**body, "name": " "}).status_code == 422
        )
        people = client.get("/office/people", headers={"X-User-Id": "alex"}).json()
        assert len(people) == 1
        assert people[0]["is_current"] is True
        assert people[0]["registered"] is True
        assert client.delete("/office/people/alex").status_code == 204
        assert client.delete("/office/people/alex").status_code == 404
        assert len(client.get("/office/people").json()) == 1
