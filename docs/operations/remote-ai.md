# Remote vision interface contract

Optional, administrator-configured and disabled by default. This is a compatible
vision-server interface, **not** a claim that every OpenAI-style provider,
Ollama endpoint or text-only model works. No external provider has been qualified
in this revision; transport tests use a local mock. Prefer the separate local
CPU container when keeping all processing on one machine is the objective.

## Required server behavior

`BOXEN_AI_BASE_URL` is the server root, optionally including a path prefix.
Do not append `/v1`: the adapter appends it. For example, root
`https://vision.example.test/inference` yields:

| Request | Required response |
| --- | --- |
| `GET /inference/v1/models` | JSON object with `data` array containing an object whose `id` exactly matches the manifest's `model.id`. Bounded readiness timeout: two seconds. |
| `POST /inference/v1/chat/completions` | Non-streaming JSON envelope with `choices[0].message.content` containing the requested JSON object as a string. `finish_reason` must be `stop` (or omitted for legacy compatibility); `length` invokes the bounded retry. |

The request includes the versioned inventory system prompt, user text and an
`image_url` data URI containing a freshly encoded, metadata-free JPEG. It sends
`model`, `temperature`, `seed`, `max_tokens`, `stream:false`, and a strict
`response_format` JSON-schema request. Remote mode omits llama.cpp-specific
`chat_template_kwargs`. The server/model must support multimodal input and this
structured-output contract; there is no prompt-only fallback. Do not enable
unbounded reasoning that consumes the response budget without an answer.

The compact output schema is `GENERATION_SCHEMA` in
[the adapter](../../backend/boxen/analysis/infrastructure/vision.py): scene quality,
summary, warnings, and at most 80 items with name, nullable quantity, confidence
and visible evidence. Boxen expands it to the persistent observation schema,
validates it and proposes a chip set. It never confirms inventory automatically.

One request uses the manifest's initial token budget; a length-truncated result
can retry once at its maximum, within the same overall `BOXEN_AI_TIMEOUT` (at
most 300 seconds). Defaults in the provisioned CPU profile are 2048/4096 tokens
and a 768-pixel longest edge. HTTP envelopes are limited to 512 KiB and model
output to 128 KiB. Invalid, oversized, truncated or failed results create no
partial inventory. Errors do not echo remote bodies or bearer credentials.

## Metadata and provenance

Store the matching version-1 manifest at
`BOXEN_AI_MODELS_DIR/BOXEN_AI_PROFILE/manifest.json`. A manifest copied from the
matching checksum-provisioned local profile is valid when the remote server
actually uses those same artifacts and model alias. Only the manifest is needed
on Boxen; no weights, executable or license files are opened in remote mode.
The manifest still retains license names, relative artifact paths, prompt/schema
hashes, resource limits, model/projector/runtime IDs and actual 64-hex artifact
digests. Never substitute a hash of the model name or an arbitrary placeholder.

These identities are **operator-reported and not locally verified or remotely
attested**. Model listing confirms an ID, not the bytes of the loaded weights.
This distinction appears in readiness messages and stored run provenance.
An opaque provider that cannot supply the required model identity is outside
this revision's supported contract. Pin the remote deployment independently;
drain/cancel queued jobs before changing its endpoint or artifacts.

## Configuration and secrets

Use `BOXEN_AI_MODE=remote`, an explicit base URL, a selected profile and its
metadata directory. The Compose remote overlay adds the required network route.
Local mode retains its restricted local endpoints. There is no browser setting
that can redirect image requests to an arbitrary address.

HTTPS certificate validation is enabled with normal trust by default.
`BOXEN_AI_CA_FILE` selects a public CA PEM bundle inside the container; it does
not disable verification. No redirect following, environment proxy discovery,
browser CORS access to inference, or automatic provider fallback is enabled.
Plain HTTP requires `BOXEN_AI_ALLOW_INSECURE_HTTP=true`; only use that on an
explicitly trusted network, since photos, prompts and credentials are unencrypted.

`BOXEN_AI_API_KEY_FILE` is an optional file containing one bearer token. Keep it
readable by UID10001 and unavailable to unrelated users. The adapter accepts
printable ASCII without spaces/control characters, with an optional single
terminal LF/CRLF, and a maximum token length of 4096 bytes. Empty, multiline,
oversized or non-regular secret files fail closed. Do not pass a token value in
an environment variable or embed credentials in the endpoint URL.

The optional Compose auth and CA overlays mount files at
`/run/secrets/boxen_ai_api_key` and `/run/secrets/boxen_ai_ca`. Their interpolation
variables name existing host files, not secret values. Protect metadata and
secrets from unauthorized replacement; changing them changes the trust boundary.

## Privacy and availability

Requested analysis sends the selected resized photo and inventory prompt to the
configured server. Stored originals, box descriptions, accounts and the whole
inventory are not part of the inference payload. The browser still connects
only to Boxen. The server operator controls retention, logs and access on that
other machine; Boxen cannot enforce them.

The UI shows a remote-analysis notice, and `/api/v1/system` reports
`runtime_offline:false` for remote mode, including a LAN endpoint. This is an
explicit exception to the same-host/offline default, not a hidden dependency.
Remote unavailability degrades analysis only. Photos, search, labels, manual
editing and previously queued review suggestions remain local and usable.
