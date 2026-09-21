from boxen.shared.errors import require
from boxen.shared.values import now


def require_lease(job: dict, lease: str) -> None:
    require(
        job["state"] == "running" and job["lease_token"] == lease and job["lease_expires_at"] > now(),
        "analysis.lease_lost",
        "This worker no longer owns the analysis job.",
    )


def require_pending(observation: dict) -> None:
    require(
        observation["decision"] == "pending",
        "observation.already_decided",
        "This suggestion has already been reviewed.",
    )
