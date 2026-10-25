# AI models — plugging your own backbone

Coach Running uses an **OpenAI-compatible** chat endpoint. You can register
several models and switch between them in the coach UI.

## Two files, two jobs

| File | Contains | Secret? |
|---|---|---|
| `models.json` | models shipped with the app: base URL, model name, roles, temperature, maxTokens, and the **name** of the env var holding the key | No |
| `models.local.json` | models **you added from the UI**, same shape | No, but gitignored (it is your data) |
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

What happens on submit:

1. The metadata is appended to **`models.local.json`** (gitignored).
2. The key is written to **`.env`** as `COACH_MODEL_<ID>_KEY`, and the file is
   `chmod 600`. It is **never** written to the database and **never** returned
   to the browser — the response only says whether the model is configured.
3. The registry reloads, and the new model is selected.

Models added this way can be removed with
`DELETE /api/coaching/models/<id>`. Models from `models.json` are shipped and
cannot be removed from the UI — edit that file instead.

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
- **chatPath** (optional) — defaults to `/chat/completions`; override it if your
  gateway exposes a different path (e.g. `/v1/chat/completions`).

> Several models can share the same key. For example `albert-qwen` and
> `deepseek-v4-flash-1017` both use `ALBERT_API_KEY`. Confirm the exact `model`
> id against `GET <apiBase>/models` with your key; if the catalogue uses a
> different id (e.g. `deepseek-ai/DeepSeek-V4-Flash-1017` or `deepseek-flash`),
> change that one field.

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
| Empty answer on a thinking model | Raise `maxTokens` or use a non-thinking model. |
| Timeout | Raise `COACH_LLM_TIMEOUT_S`. |
