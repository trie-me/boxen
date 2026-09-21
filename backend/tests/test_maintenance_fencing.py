from boxen.operations import application as maintenance
from boxen.shared.values import after, now


def test_expired_maintenance_cannot_commit_rebuild_or_terminal_status(client, monkeypatch):
    app = client.app.state.services
    client.post("/api/v1/boxes", json={"name": "Lease fixture"})
    with app.database.transaction(write=True) as repo:
        repo.execute("DELETE FROM box_search")
    requested = client.post("/api/v1/maintenance/search/rebuild")
    assert requested.status_code == 202, requested.text
    job_id = requested.json()["id"]
    original = maintenance.verify_search
    expired_time = after(120, now())

    def expire_after_work(repo, rebuild=False):
        result = original(repo, rebuild)
        monkeypatch.setattr(maintenance, "now", lambda: expired_time)
        return result

    monkeypatch.setattr(maintenance, "verify_search", expire_after_work)
    assert app.operations.run_once()
    with app.database.transaction() as repo:
        assert not repo.rows("SELECT * FROM box_search")
        assert repo.one("maintenance_jobs", id=job_id)["state"] == "running"
        assert repo.one("maintenance_jobs", id=job_id)["result_json"] is None
