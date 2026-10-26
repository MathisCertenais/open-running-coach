# AI models — plugging your own backbone

Coach Running uses an **OpenAI-compatible** chat endpoint. You can register
several models and switch between them in the coach UI.

## Two files, two jobs

| File | Contains | Secret? |
|---|---|---|
| `models.json` | models shipped with the app: base URL, model name, roles, temperature, maxTokens, and the **name** of the env var holding the key | No |
| `models.local.json` | models **you added**, your edits to shipped ones, and the shipped ones you deleted | No — gitignored (your data) |
| `.env` (or the OS environment) | the actual API keys | **Yes** — gitignored |

The backend resolves the key from the environment and proxies every request.
Keys are **never** written to SQLite, returned by the API, or sent to the
browser.

## Example `models.json`

```json
{
  "default": "albert-qwen",
  "models": [
    {
      "id": "albert-qwen",
      "name": "Albert Qwen",
      "provider": "openai",
      "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
      "apiBase": "https://albert.api.etalab.gouv.fr/v1",
      "apiKeyEnv": "ALBERT_API_KEY",
      "roles": ["chat", "edit", "apply"],
      "temperature": 0.4,
      "maxTokens": 900
    },
    {
      "id": "gemma-4-31b",
      "name": "Gemma 4 31B (ragarenn)",
      "provider": "openai",
      "model": "ilaas/gemma-4-31b",
      "apiBase": "https://ragarenn.eskemm-numerique.fr/sso/ch@t/api",
      "apiKeyEnv": "GEMMA_API_KEY",
      "roles": ["chat", "edit", "apply"],
      "temperature": 0.4,
      "maxTokens": 900
    }
  ]
}
```

## Keys

```env
# .env (never commit)
ALBERT_API_KEY=sk-...
GEMMA_API_KEY=sk-...
```

For the packaged app, the file lives in `~/CoachRunning/.env`. You can also
export the variables in your shell or use your OS keychain to inject them.

## Adding a model from the UI

You do not have to edit files. In the coach panel, open the **Model** dropdown
and choose **＋ New model…**. The form asks for:

| Field | Example | Notes |
|---|---|---|
| Display name | `My gateway` | what the selector shows |
| Model id | `gpt-4o-mini` | exactly what the provider expects |
| Base URL | `https://api.example.com/v1` | the prefix before `/chat/completions`; must be `http` or `https` |
| API key | `sk-…` | leave empty for a local server such as Ollama |
| Chat path (advanced) | `/chat/completions` | only if your gateway uses a different path |
| Extra headers (advanced) | `{"x-opencode-session": "{session}"}` | JSON object; for gateways that need a routing hint (see below) |

What happens on submit:

1. The metadata is appended to **`models.local.json`** (gitignored).
2. The key is written to **`.env`** as `COACH_MODEL_<ID>_KEY`, and the file is
   `chmod 600`. It is **never** written to the database and **never** returned
   to the browser — the response only says whether the model is configured.
3. The registry reloads, and the new model is selected.

Every model can be **edited** and **deleted** from the same panel: select it,
then use **Edit** or **Delete** next to the selector.

- **Edit** reopens the form, pre-filled. The key field starts empty and means
  *keep the stored key*: the browser never receives it, so it cannot resend it.
  Typing a new key rotates the same `COACH_MODEL_<ID>_KEY` line in place.
- **Delete** asks for confirmation, removes the entry from
  `models.local.json`, and also removes its key line from **`.env`** so no
  orphaned secret is left on disk.

**Shipped models are editable too.** `models.json` is versioned and is never
rewritten by the app. Editing one of its entries writes an *override* with the
same id into `models.local.json` (which wins on load), and deleting one adds its
id to `hidden` there. So:

- `git status` stays clean and `git pull` still brings you new shipped models;
- **Restore** (next to the selector, shown only when something is hidden) brings
  the deleted shipped models back;
- a new key typed on a shipped model is stored under
  `COACH_MODEL_<ID>_KEY`, never in the shared variable (`ALBERT_API_KEY` and the
  like) that other shipped models may use;
- deleting a model never removes a `COACH_MODEL_*` variable another model still
  reads, and never deletes a shared shipped variable at all.

`list_models()` reports where each entry lives: `source` is `shipped`,
`override` (shipped, changed locally) or `local` (added from the UI).

The id is stable: renaming a model does not change it, so the selection saved
in the browser and the env var keep pointing at the same entry.

Equivalent API: `PUT /api/coaching/models/<id>` (edit), `DELETE
/api/coaching/models/<id>` (delete), `POST /api/coaching/models/restore` (bring
back every hidden shipped model). Unknown ids answer 404.

### When the coach cannot reach the endpoint

The request is a plain `POST <apiBase><chatPath>` with `Authorization: Bearer`.
Two failures are worth recognising:

- **`HTTP 403 … error code: 1010`** — a Cloudflare-fronted gateway rejected the
  request before it reached the model. The client sends
  `User-Agent: coach-running/1.0` for this reason; urllib's default
  (`Python-urllib/3.x`) is blocked outright.
- **`HTTP 400 … MissingSessionID`** — the endpoint is not a plain
  OpenAI-compatible gateway: `https://opencode.ai/inference/go/openai/v1` routes
  by session and needs an `x-opencode-session` header. Add it as an extra
  header (see *Endpoints that need extra headers* below), or point the model at
  a real OpenAI-compatible URL.

The error text from the provider is shown in the chat, so check it before
assuming the key is wrong.

## Fields

- **id** — stable identifier used by the UI and the API.
- **name** — label shown in the model selector.
- **model** — the provider's model id.
- **apiBase** — the prefix before `/chat/completions`.
- **apiKeyEnv** — the **name** of the env var holding the key (empty for local
  servers such as Ollama).
- **roles** — `chat` is used today; `edit`/`apply` are reserved for future
  plan-editing features.
- **temperature**, **maxTokens** — per-model request settings.
- **tools** — function calling: `true` (default) sends all eleven tool schemas,
  `false` disables them, and an integer sends only the first N in priority order
  (`search_activities`, `get_activity`, `best_efforts`, `get_sessions`, …). Small
  local models are cheaper and more reliable with three: `"tools": 3`.
- **chatPath** (optional) — defaults to `/chat/completions`; override it if your
  gateway exposes a different path (e.g. `/v1/chat/completions`).
- **headers** (optional) — extra request headers, for gateways that need a
  routing hint. `{session}` is replaced by a stable id generated when the server
  starts, so prompt caching works within a run; `$uuid` is replaced by a fresh
  UUID4 on every request, for gateways that want a per-request id. `Authorization`,
  `Content-Type`, `Content-Length` and `Host` are managed by the app and are
  rejected: this field is **not** a place for secrets, which belong in the API
  key field (they are written to `.env`, headers are written to
  `models.local.json` in clear text).

> Several models can share the same key: `albert-qwen`, `gemma-4-31b` and any
> model you add can point at the same `apiKeyEnv`. Confirm the exact `model` id
> against `GET <apiBase>/models` with your key; if the catalogue uses a
> different id (e.g. `Qwen/Qwen3-Coder-30B-A3B-Instruct` vs `qwen3-coder`),
> change that one field. A model that appears in the catalogue but answers with
> an error from the provider is not registered here — see the troubleshooting
> table.

### Endpoints that need extra headers (OpenCode Go)

`https://opencode.ai/inference/go/openai/v1` is not a plain OpenAI-compatible
gateway: it routes by session and answers `400 MissingSessionID` unless the
request carries `x-opencode-session`. Its [docs](https://opencode.ai/docs/go/)
ask clients to send a stable session id per conversation and to identify
themselves with their own user agent — the app now sends
`User-Agent: coach-running/1.0` on every request.

Set it once on the model, in **Advanced → Extra headers**:

```json
{"x-opencode-session": "{session}"}
```

Equivalently, in `models.local.json`:

```json
{
  "id": "opencode-deepseek-flash",
  "name": "OpenCode DeepSeek Flash",
  "model": "deepseek-v4.1-flash",
  "apiBase": "https://opencode.ai/inference/go/openai/v1",
  "apiKeyEnv": "COACH_MODEL_OPENCODE_DEEPSEEK_FLASH_KEY",
  "headers": {"x-opencode-session": "{session}"}
}
```

Any stable value works (`{session}` simply keeps it distinct per server run);
the header is a routing hint, not a credential.

> OpenCode Go targets coding agents: "traffic is monitored for abuse that
> degrades the experience for other users". A training coach is not the
> workload it was built for, so expect rate limits and read their terms before
> pointing your whole training history at it.

## Default and switching

- `models.json` → `"default": "<id>"` sets the preferred model.
- `COACH_LLM_DEFAULT` overrides it.
- If the default is missing a key, the app falls back to the first configured
  model and disables the others in the selector.
- The coach panel (Home and Coaching → Coach) has a **Model** dropdown; the
  choice is remembered in the browser.

## Local Ollama

Ollama needs no key. It is registered in `models.json` as `ollama-local`
(`http://127.0.0.1:11434/v1`). Keep it as a private/offline fallback.

## Evaluating models

Picking between the models you registered is a measurement, not an opinion. The
repository ships a benchmark harness that asks every candidate the same five
coach questions about three frozen synthetic athletes, scores the answers against
a fixed rubric and writes a report. It is developer tooling: it never runs inside
the app, and it never sends your own data anywhere. See
[`AI_BENCHMARK.md`](AI_BENCHMARK.md) for how to run a sweep, how to add a model
to the roster and how to read the result.

## Security notes

- `models.json` is safe to share/commit; it never contains keys.
- `.env` is gitignored and excluded from the packaged bundle.
- The API returns model names and a `configured` flag only.
- Errors are returned without echoing the key.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Model shows “(missing key)” | Add the key to `.env` and restart. |
| `401` | Wrong key for that provider. |
| `404` | Check `apiBase` / `chatPath` (the base must be the prefix before `/chat/completions`). |
| The model is listed by `GET <apiBase>/models` but the provider rejects it on chat | The catalogue can advertise a model the chat endpoint will not serve. Remove that entry from `models.json` or switch to an id the provider documents. The `deepseek-v4-flash-1017` entry was listed by Albert but rejected on every chat call, which is why it is no longer shipped. |
| Empty answer on a thinking model | Raise `maxTokens` or use a non-thinking model. |
| Timeout | Raise `COACH_LLM_TIMEOUT_S`. |
