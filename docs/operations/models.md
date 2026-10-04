# Local vision AI

The native Linux x86-64 CPU path has been exercised with real Qwen3-VL image inference and the full Boxen review/accept/search workflow. See [the current photo-collection repair](../verification/ai-photo-collection.md) and [original verification record](../verification/ai-local-cpu.md) for evidence and limitations. Suggestions always require review: the small model can miss or misidentify objects and quantities. The compact v3 path leaves detailed attributes and bounding boxes null.

Fresh installations require explicit provisioning. Neither web nor worker
downloads models or starts inference. Local mode calls no external AI service;
the new explicitly enabled [remote mode](remote-ai.md) is an optional exception.
Manual inventory remains available when inference is stopped. For Docker use
the [separate model container](deployment.md#separate-local-model-container).

## Start the provisioned native installation

On the verified host, the existing user data directory is `/path/to/boxen/.local/boxen/data`. Its profile is `models/qwen3-vl-2b-q4-cpu`; the older `.runtime` directory was not changed. From the project directory, export these in **each** runtime, web and worker terminal or service environment:

```sh
export BOXEN_DATA_DIR=/path/to/boxen/.local/boxen/data
export BOXEN_AI_PROFILE=qwen3-vl-2b-q4-cpu
export BOXEN_AI_BASE_URL=http://127.0.0.1:8080
```

Start inference in its own foreground terminal or supervisor:

```sh
.venv/bin/python -m boxen.analysis.infrastructure.runtime --threads 8
```

The launcher verifies model, projector, executable, bundled-library and prompt/schema hashes, then replaces itself with the pinned server. It binds only `127.0.0.1:8080`, uses eight CPU threads and one slot, disables the web UI, restricts CORS, and sets `--offline` with local artifact paths. Inherited model-download, RPC and inference options are removed. Ctrl-C stops foreground inference. The launcher does not detach or install a boot service. `--print-command` prints its exact argument list without launching; `--port 18080` selects an isolated test port.

Restart web and worker with the same three variables. For this host's existing trusted-LAN development setup, the commands in two further terminals are:

```sh
BOXEN_ENV=development BOXEN_ORIGIN=http://192.0.2.10:8000 \
  .venv/bin/boxen web --host 192.0.2.10 --port 8000
```

```sh
BOXEN_ENV=development BOXEN_ORIGIN=http://192.0.2.10:8000 \
  .venv/bin/boxen worker
```

Use your own host/origin on another installation. Do not start duplicates when a supervisor already owns the port or worker. Runtime `/health` is only readiness: upload a photo, request analysis, inspect suggestions, and explicitly accept/correct the desired objects to create inventory.

## Reproduce provisioning

[The source lock](../../profiles/qwen3-vl-2b-cpu.sources.json) records official revisions, URLs, exact download sizes and hashes, and license provenance. The model/projector total is 1,552,463,168 bytes; the CPU archive adds 16,845,642 bytes. Allow roughly 3.2 GiB for retained downloads and the copied profile. This Linux binary is not a macOS/Windows runtime.

1. Download the five `artifacts` from the source lock into project-local `.local/ai-downloads`. Network is needed only for provisioning. No global installer or runtime model downloader is needed.
2. Compare each file's `sha256sum` with the source lock before extracting or running anything. Model/projector hashes came from upstream Hugging Face LFS metadata; the archive hash came from the official GitHub release metadata.
3. Extract the verified archive inside `.local/ai-downloads` using `tar -xzf .local/ai-downloads/llama-b10977-bin-ubuntu-x64.tar.gz -C .local/ai-downloads --no-same-owner`.
4. With `BOXEN_DATA_DIR` pointing to the intended existing installation, run:

```sh
.venv/bin/python scripts/provision_profile.py \
  --profile qwen3-vl-2b-q4-cpu \
  --model .local/ai-downloads/Qwen3VL-2B-Instruct-Q4_K_M.gguf \
  --projector .local/ai-downloads/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf \
  --runtime .local/ai-downloads/llama-b10977/llama-server \
  --runtime-version b10977-0ecb159c9 \
  --runtime-library .local/ai-downloads/llama-b10977/lib*.so* \
  --license .local/ai-downloads/Apache-2.0.txt \
  --license .local/ai-downloads/llama-LICENSE \
  --display-name 'Qwen3-VL 2B Q4 CPU'
```

The helper copies explicitly selected local files, preserves library loader names, pins hashes and refuses to overwrite an existing profile. Defaults are a 768-pixel image edge, 2,048 initial output tokens and a 4,096-token ceiling, temperature zero and seed zero. A truncated response gets one larger-budget retry within the same overall time limit; no partial inventory is accepted. `qualification: unqualified` distinguishes artifact integrity and an operational smoke test from broad accuracy evaluation.

Prompt contracts are pinned too. The verified native installation has been updated to `inventory-v3`; stale v2 manifests intentionally fail verification under v3 application code. For another installation, provision a new profile name from the already-downloaded local files using the current helper, then configure web/worker/runtime to that profile. No weights need to be downloaded again. Do not change artifact hashes to hide mismatches.

Copying only `llama-server` is insufficient: the release uses `$ORIGIN` to find its shared libraries. The host also needs normal system C/C++ libraries, OpenSSL3, zlib and libgomp. `ldd` on this host found no missing dependencies. No global package manager, runtime or model cache was changed.

## Repeat real inference and review

Download and hash-check the source lock's CC0 `verification_photo` once. With inference running:

```sh
BOXEN_REAL_AI_PROFILE_ROOT="$BOXEN_DATA_DIR/models/$BOXEN_AI_PROFILE" \
BOXEN_REAL_AI_COFFEE_IMAGE="$PWD/.local/ai-downloads/coffee.png" \
BOXEN_REAL_AI_URL="$BOXEN_AI_BASE_URL" \
  .venv/bin/python -m pytest backend/tests/test_ai_real_model.py -s
```

The test uses a disposable database/media store and an anonymous editor session before owner setup. It asserts `setup_required: true` and zero owners, uploads the photograph, runs actual inference through `LocalVision` and the normal worker, asserts pending suggestions and empty inventory, then issues an explicit review acceptance and verifies the AI-provenance cup is searchable. Setup remains incomplete afterward. It exercises the review API; it does not claim a browser user personally clicked Accept. It skips without `BOXEN_REAL_AI_PROFILE_ROOT`, so ordinary unit tests are not evidence of model recognition.

## Errors and other deployments

Invalid artifacts or a stale prompt manifest produce `ai.profile_invalid`; stopped inference produces `ai.runtime_unavailable`. Exhausting the larger output budget produces `ai.output_truncated` with advice to use closer photos of smaller groups; it does not cause an identical whole-job retry. Truncated, malformed, oversized or schema-invalid responses create no suggestions. Unset `BOXEN_AI_PROFILE` and restart web/worker to disable AI. Do not replace weights under a running process.

Compose now supplies a private `boxen-ai` service through its local-AI overlay,
with a separate read-only `/models` volume and no published AI port. Use
`BOXEN_AI_MODELS_DIR` to override the native `$BOXEN_DATA_DIR/models` default.
The runtime launcher binds loopback unless explicitly passed `--host 0.0.0.0`
inside that private container network; it refuses remote mode. Container
loopback is not host loopback. See [container evidence](../verification/containers.md)
for the new image checks; this older native CPU record does not qualify GPU,
macOS or Windows. `--offline` prevents runtime provisioning, not all possible
egress at the operating-system level.
