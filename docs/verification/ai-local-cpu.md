# Real local CPU vision verification — 2026-09-20

This records the original `inventory-v2` smoke test. The deployed `inventory-v3`
path, compact output, token-limit repair and collective-photo workflow are covered
in [the subsequent verification record](ai-photo-collection.md). Attribute and
bounding-box generation described below is historical, not the current path.

**Result:** real model inference and the image → pending suggestions → explicit review acceptance → searchable inventory workflow passed. This replaces the previous adapter-only evidence. It is an operational smoke test on one public photograph, not an accuracy qualification or a claim that a human clicked through the browser.

## Host, artifacts and installation

- Host: Linux x86-64, AMD Ryzen 9 9950X, 16 cores/32 threads, about 23 GiB RAM available at inspection. NVIDIA driver was unavailable; inference used CPU only, eight threads and one slot.
- Initial state: `.runtime/models` empty, no known Ollama/Hugging Face/llama.cpp cache or executable; loopback ports 8080, 11434 and 1234 refused connections.
- Model: official Qwen3-VL-2B-Instruct Q4_K_M, Q8 projector, repository revision `52d6c8ffea26cc873ac5ad116f8631268d7eb503`, Apache-2.0.
- Runtime: official llama.cpp Linux CPU release b10977, reported `0.4.1-dev (build 10977, commit 0ecb159c9)`, MIT.
- Downloaded under ignored `.local/ai-downloads`; installed at `.local/boxen/data/models/qwen3-vl-2b-q4-cpu`. The installed profile retains model/projector/runtime/library hashes and both license texts. No global installation/cache changes, no `.runtime` changes, no user inventory mutations.
- Exact sources, file sizes, hashes and license declarations: [source lock](../../profiles/qwen3-vl-2b-cpu.sources.json). All three binary downloads matched upstream hashes. `ldd` found no missing runtime dependencies; bundled libraries resolve beside the executable via `$ORIGIN`.
- Model/projector/runtime downloads total **1,569,308,810 bytes**; retained staging and installed profile each occupy about 1.6 GiB.

The source is [Qwen's official GGUF repository](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/52d6c8ffea26cc873ac5ad116f8631268d7eb503) and [the official llama.cpp b10977 release](https://github.com/ggml-org/llama.cpp/releases/tag/b10977). Reproducible native start/provision/test commands are in [models.md](../operations/models.md).

## Real photograph and observed output

Photo: scikit-image v0.25.2 `coffee.png`, 600 × 400, Rachel Michetti, courtesy of Pikolo Espresso Bar. The upstream [photo documentation declares CC0](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/_fetchers.py#L912-L928). It was downloaded during provisioning and visually inspected before review: one red/brown cup, matching saucer and silver spoon on a wooden table; there is no readable printed object text.

Photo SHA-256: `cc02f8ca188b167c775a7101b5d767d1e71792cf762c33d6fa15a4599b5a8de7`.

The final model response said `scene_quality: good`, summary “A coffee cup and saucer with a spoon on a wooden table.”, warning `glare`. Actual observations were:

| Model name | Quantity | Confidence | Returned visible_text | Review finding |
| --- | --- | --- | --- | --- |
| coffee cup | 1 | 0.85 | espresso | Correct object; text invented |
| saucer | 1 | 0.85 | espresso | Correct object; text invented |
| spoon | 1 | 0.85 | espresso | Correct object; text invented |
| table | 1 | 0.85 | wood | Visible background, unwanted inventory suggestion |

The model also returned `brand: "unknown"`, `model: "unknown"` instead of null and inaccurate bounding boxes. For example, cup and saucer both had `{x:0.25,y:0.15,width:0.25,height:0.25}`. These are schema-valid but semantically unreliable. A strengthened prompt did not eliminate these defects. No output was silently repaired or represented as more accurate than received.

## Workflow assertions and timing

`backend/tests/test_ai_real_model.py` uses real `LocalVision`, HTTP to the provisioned model, and `worker.tick(..., schedule=False)` including normal lease renewal. No fake adapter, HTTP mock or canned model output is used. The initial two runs below used the existing owner-session client fixture. The final test has since been changed to initialize a disposable installation with anonymous editor access, assert `setup_required: true` and zero owners, and acquire ordinary browser-session cookies and CSRF before any upload/job. Owner setup remains incomplete after review.

1. Create a box in the pytest temporary database and upload the real photograph through the photo API.
2. Queue analysis through the API and run the normal worker tick.
3. Assert the job succeeded, model/input provenance was recorded and all four suggestions are pending.
4. Assert **zero** inventory items before review.
5. Identify the visually confirmed cup suggestion, submit the explicit review endpoint with reviewed name `Coffee cup`, quantity `1`, unit `piece`.
6. Assert exactly one inventory item with `provenance: ai` and a successful search for `Coffee cup`. Other suggestions remain unaccepted.

First owner-session run: **1 passed in 18.10 s**, inference **17,090 ms**. Final-prompt owner-session run: **1 passed in 18.21 s**, inference **17,234 ms**. The latter runtime reported 993 prompt tokens, 644 generated tokens and about 43.17 generated tokens/second. These are single-photo observed timings, not performance guarantees.

Final **anonymous-before-setup** run against the supervised runtime at `127.0.0.1:8080`: **1 passed in 18.08 s**, inference **17,136 ms**. No owner account existed; the anonymous editor completed creation, photo upload, analysis, explicit review and searchable inventory acceptance. `setup_required` remained true after review. The database and uploaded media were disposable pytest fixtures; no live inventory was changed. JUnit evidence: `artifacts/tests-real-ai-anonymous.xml` (18.040 s suite timing, excluding pytest overhead).

Final inference provenance:

| Field | Value |
| --- | --- |
| Prompt | `inventory-v2` |
| Prompt SHA-256 | `d59ad89fcaa3081a0c0b9d3c9a1d631c33a53c90e2b2cf122668eb75ba43eb07` |
| Output schema SHA-256 | `67a446ecd56bfad2e868152821299a2a8b795022ea863a6fc19bf17b01492c3d` |
| Preprocessing | `pillow-jpeg-v2` |
| Actual JPEG input SHA-256 | `c01741233ebc755757e6499cabd54714747b56d13eaeeecee7259ef00264250b` |
| Runtime executable SHA-256 | `559add11ec32453022d9e267f62143e78ff9992f8bbeceda939cc62fcfed3cbb` |
| Parameters | image edge 768; output tokens 2048; temperature 0; seed 0 |

## Changes and remaining scope

The adapter now transcodes stored WebP display images into metadata-free JPEG supported by llama.cpp, exposes the output schema to the model as well as its decoding grammar, rejects token-truncated output and records the actual preprocessing version. Provisioning copies and validates shared libraries. The new foreground launcher selects only pinned local files, CPU execution, loopback binding and offline mode.

Focused adapter/provisioning/review/runtime-setup suite: **18 passed**. Ruff and focused mypy checks pass. The restricted sandbox stalled the in-process web fixture; the scoped host run completed in under a second. Real inference was explicitly run with host loopback access.

Both temporary inference processes were stopped; final test port `127.0.0.1:18080` refused connections afterward. No detached inference was left by this test. The parent task reports supervised inference active and healthy at `127.0.0.1:8080`, with web on `192.0.2.10:8000` and worker using `.local/boxen/app.toml`. The parent owns these services and their lifetime; this record does not imply boot persistence.

The profile retains `qualification: unqualified`. Remaining limits include one-photograph coverage, inaccurate grounding/text, no private inventory corpus, no accelerator/other-platform/container verification, and no OS-level egress-isolation audit. All inference requests used the loopback endpoint, embedded image bytes and local files; external access was used only to provision artifacts, licensing and this public test photograph.
