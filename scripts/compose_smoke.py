"""Disposable HTTPS deployment/persistence smoke; never targets an existing project.

Requires locally built images and a host Python with httpx/Pillow. No image pull,
model download, public network request or host trust-store modification. Creates
and removes only a fresh, uniquely named Compose project and its test volumes.
"""

import argparse
import io
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="boxen:container-dev")
    parser.add_argument("--proxy-image", default="boxen-caddy:container-dev")
    parser.add_argument("--port", type=int, default=18743)
    parser.add_argument("--model-image", default="boxen-ai:container-dev")
    parser.add_argument("--model-profile", type=Path, help="Existing provisioned profile; copied read-only")
    parser.add_argument("--fixture-image", type=Path, help="Public coffee-cup test photo, not personal data")
    parser.add_argument("--tailnet-host", help="Host's existing Tailscale DNS name; enables tailnet overlay")
    parser.add_argument("--tailnet-ipv4")
    parser.add_argument("--tailnet-ipv6")
    parser.add_argument("--legacy-ipv4")
    parser.add_argument("--http-port", type=int, default=18080)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged test port.")
    if bool(args.model_profile) != bool(args.fixture_image):
        parser.error("Real AI testing requires both --model-profile and --fixture-image.")
    bind_address = "127.0.0.1"
    if args.tailnet_host:
        if not all((args.tailnet_ipv4, args.tailnet_ipv6, args.legacy_ipv4)):
            parser.error("Tailnet smoke requires both Tailscale addresses and the previous LAN IPv4.")
        ipaddress.IPv4Address(args.tailnet_ipv4)
        ipaddress.IPv6Address(args.tailnet_ipv6)
        ipaddress.IPv4Address(args.legacy_ipv4)
        if not 1024 <= args.http_port <= 65535 or args.http_port == args.port:
            parser.error("Choose distinct unprivileged HTTP/HTTPS test ports.")
        bind_address = args.tailnet_ipv4
    for address in [bind_address, *([args.legacy_ipv4, args.tailnet_ipv6] if args.tailnet_host else [])]:
        for port in [args.port, *([args.http_port] if args.tailnet_host else [])]:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            with socket.socket(family) as probe:
                probe.bind((address, port))
    root = Path(__file__).resolve().parents[1]
    project = "boxen-smoke-" + uuid.uuid4().hex[:12]
    origin = f"https://{args.tailnet_host or 'localhost'}:{args.port}"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("BOXEN_", "COMPOSE_"))}
    env.update(
        BOXEN_IMAGE=args.image,
        BOXEN_CADDY_IMAGE=args.proxy_image,
        BOXEN_HOST=args.tailnet_host or "localhost",
        BOXEN_BIND_ADDRESS=bind_address,
        BOXEN_HTTPS_PORT=str(args.port),
        BOXEN_ORIGIN=origin,
        BOXEN_ANONYMOUS_ACCESS="editor",
    )
    base = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        project,
        "-f",
        str(root / "deploy/compose.yaml"),
    ]
    services = ["web", "worker", "caddy"]
    if args.tailnet_host:
        env.update(
            BOXEN_TAILNET_IPV6=args.tailnet_ipv6,
            BOXEN_LEGACY_HOST=args.legacy_ipv4,
            BOXEN_HTTP_PORT=str(args.http_port),
        )
        base.extend(["-f", str(root / "deploy/compose.tailnet.yaml")])
    if args.model_profile:
        args.model_profile = args.model_profile.resolve(strict=True)
        args.fixture_image = args.fixture_image.resolve(strict=True)
        profile_id = json.loads((args.model_profile / "manifest.json").read_text())["profile_id"]
        env.update(BOXEN_AI_IMAGE=args.model_image, BOXEN_AI_PROFILE=profile_id)
        base.extend(["-f", str(root / "deploy/compose.ai-local.yaml")])
        services.append("boxen-ai")

    def compose(*parts, sensitive=False):
        result = subprocess.run(base + list(parts), env=env, capture_output=True, text=True, timeout=360)
        if result.returncode:
            # init output may contain a one-time setup credential; never echo it.
            detail = " (output suppressed)" if sensitive else "\n" + result.stderr[-3000:]
            raise RuntimeError("Compose command failed: " + " ".join(parts[:3]) + detail)
        return result.stdout

    def until(check, seconds=40):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if result := check():
                    return result
            except (httpx.HTTPError, AssertionError, RuntimeError):
                pass
            time.sleep(0.5)
        raise AssertionError("Timed out waiting for the disposable deployment.")

    with tempfile.TemporaryDirectory(prefix=project + "-") as work:
        ca = Path(work) / "root.crt"
        try:
            compose("config", "--quiet")
            if args.model_profile:
                print("Importing a copy of the verified model into a disposable volume…", flush=True)
                compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "--pull",
                    "never",
                    "--volume",
                    f"{args.model_profile}:/source:ro",
                    "model-import",
                )
            compose("run", "--rm", "--no-deps", "--pull", "never", "init", sensitive=True)
            print("Starting disposable HTTPS deployment…", flush=True)
            compose(
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "180",
                *services,
            )
            until(
                lambda: (
                    compose("cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(ca)) or ca.is_file()
                )
            )
            tls = ssl.create_default_context(cafile=str(ca))
            with httpx.Client(base_url=origin, verify=tls, trust_env=False, timeout=10) as client:
                until(lambda: client.get("/api/v1/health/ready").status_code == 200)
                if args.tailnet_host:
                    for address in (
                        f"https://{args.legacy_ipv4}:{args.port}",
                        f"http://{args.legacy_ipv4}:{args.http_port}",
                        f"http://{args.tailnet_host}:{args.http_port}",
                    ):
                        redirect = client.get(address + "/boxes?lifecycle=active")
                        assert redirect.status_code == 302
                        assert redirect.headers["location"] == origin + "/boxes?lifecycle=active"
                        assert client.post(address + "/api/v1/boxes", json={}).status_code == 400
                    for suffix in ("root.key", "pki/authorities/local/root.key"):
                        assert client.get("/trust/" + suffix).status_code == 404
                    # Use the DNS SNI while explicitly exercising the IPv6 socket.
                    ipv6 = subprocess.run(
                        [
                            "curl",
                            "--fail",
                            "--silent",
                            "--show-error",
                            "--noproxy",
                            "*",
                            "--cacert",
                            str(ca),
                            "--resolve",
                            f"{args.tailnet_host}:{args.port}:[{args.tailnet_ipv6}]",
                            origin + "/api/v1/health/ready",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                    )
                    assert json.loads(ipv6.stdout)["status"] == "ready"
                assert client.get("/").status_code == 200
                session = client.get("/api/v1/session")
                assert session.json()["anonymous"] is True
                assert session.json()["user"]["role"] == "editor"
                assert "Secure" in session.headers["set-cookie"]
                client.headers.update({"Origin": origin, "X-CSRF-Token": session.json()["csrf_token"]})
                client.event_hooks["request"].append(
                    lambda request: request.headers.setdefault("Idempotency-Key", str(uuid.uuid4()))
                )
                assert client.get("/api/v1/users").status_code == 403
                box = client.post(
                    "/api/v1/boxes",
                    json={"name": "Container persistence", "description_markdown": "**Stored** safely"},
                )
                assert box.status_code == 201, box.text
                code = box.json()["code"]
                item = client.post(
                    f"/api/v1/boxes/{code}/items", json={"name": "Persistence cable", "quantity": "2"}
                )
                assert item.status_code == 201, item.text
                photo = io.BytesIO()
                Image.new("RGB", (180, 100), "green").save(photo, "PNG")
                uploaded = client.post(
                    f"/api/v1/boxes/{code}/images",
                    files={"file": ("fixture.png", photo.getvalue(), "image/png")},
                )
                assert uploaded.status_code == 201, uploaded.text
                thumbnail = uploaded.json()["thumbnail_url"]
                assert client.get(thumbnail).status_code == 200
                assert code in client.get("/api/v1/search", params={"q": "Persistence cable"}).text
                label = client.get(f"/api/v1/boxes/{code}/label.pdf?profile=roll-62x29-mm-v1")
                assert label.status_code == 200 and label.content.startswith(b"%PDF")
                batch = client.post("/api/v1/labels.pdf", json={"box_codes": [code]})
                assert batch.status_code == 200 and batch.content.startswith(b"%PDF")
                until(
                    lambda: client.get("/api/v1/system").json()["components"]["worker"]["status"] == "ready"
                )
                ai_metrics = None
                if args.model_profile:
                    until(
                        lambda: client.get("/api/v1/system").json()["components"]["ai"]["status"] == "ready"
                    )
                    print("Analyzing the public test photo through the separate model container…", flush=True)
                    ai_photo = client.post(
                        f"/api/v1/boxes/{code}/images",
                        files={"file": ("coffee.png", args.fixture_image.read_bytes(), "image/png")},
                    )
                    assert ai_photo.status_code == 201, ai_photo.text
                    requested = client.post(f"/api/v1/images/{ai_photo.json()['id']}/analyses", json={})
                    assert requested.status_code == 202, requested.text
                    job_url = "/api/v1/jobs/" + requested.json()["id"]

                    def finished_job():
                        job = client.get(job_url).json()
                        return job if job["state"] in {"succeeded", "failed", "cancelled"} else None

                    job = until(finished_job, seconds=310)
                    assert job["state"] == "succeeded", job
                    suggestions = client.get(f"/api/v1/boxes/{code}/observations").json()["items"]
                    cups = [
                        item
                        for item in suggestions
                        if any(word in item["proposed_name"].lower() for word in ("cup", "mug"))
                    ]
                    assert cups and all(item["decision"] == "pending" for item in suggestions)
                    assert len(client.get(f"/api/v1/boxes/{code}/items").json()["items"]) == 1
                    accepted = client.post(
                        f"/api/v1/observations/{cups[0]['id']}/accept",
                        json={
                            "mode": "create",
                            "item": {"name": "Verified coffee cup", "quantity": "1", "unit": "piece"},
                        },
                    )
                    assert accepted.status_code == 200, accepted.text
                    assert accepted.json()["item"]["provenance"] == "ai"
                    assert code in client.get("/api/v1/search?q=Verified%20coffee%20cup").text
                    ai_metrics = {
                        "job": "succeeded",
                        "suggestions": len(suggestions),
                        "explicit_review": "pass",
                    }
                else:
                    assert client.get("/api/v1/system").json()["components"]["ai"]["status"] == "unavailable"
                # Recreate containers, preserving only the named volumes.
                print("Checking data, sessions and certificate persistence after recreation…", flush=True)
                compose(
                    "up",
                    "-d",
                    "--no-build",
                    "--pull",
                    "never",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "web",
                    "worker",
                    "caddy",
                )
                until(lambda: client.get("/api/v1/boxes/" + code).status_code == 200)
                assert client.get("/api/v1/boxes/" + code).json()["name"] == "Container persistence"
                assert client.get(thumbnail).status_code == 200
                assert code in client.get("/api/v1/search?q=Persistence").text
                # Same CA still verifies; same session cookie still works.
                assert client.get("/api/v1/session").json()["csrf_token"] == session.json()["csrf_token"]
                if args.model_profile:
                    compose("stop", "boxen-ai")
                    until(
                        lambda: (
                            client.get("/api/v1/system").json()["components"]["ai"]["status"] == "unavailable"
                        )
                    )
                    assert client.get("/api/v1/health/ready").status_code == 200
                    assert client.get(thumbnail).status_code == 200
                    still_editable = client.post(
                        "/api/v1/boxes", json={"name": "AI outage does not block inventory"}
                    )
                    assert still_editable.status_code == 201, still_editable.text
                    ai_metrics["core_after_ai_stop"] = "pass"
            print(
                json.dumps(
                    {
                        "project": project,
                        "https_verified": True,
                        "tailnet_ipv6_and_legacy_redirects": bool(args.tailnet_host),
                        "anonymous_crud_media_search_labels": "pass",
                        "worker": "ready",
                        "recreation_persistence_and_ca": "pass",
                        "remote_calls": 0,
                        "real_container_ai": ai_metrics,
                    }
                )
            )
        finally:
            # This random project was created above; never accept a user-supplied
            # project name here. Do not prune global images/networks/volumes.
            compose("down", "--timeout", "10", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
