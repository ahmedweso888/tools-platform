# Tools Platform

Backend مستقل يجمع الأدوات المرفوعة في مشروع واحد، مع API موحد وتجهيز مباشر لـ Railway. لا يحتوي هذا المشروع على تكامل WISO، ولا Authentication/Subscription/Payment/Wallet/Admin الخاصة بـ WISO.

## Included tools

- **SPX Financial Literacy**: solver موجود أصلًا في `src/tools/sprix_financial_literacy/`.
- **Qureo Auto Solver**: solver موجود أصلًا في `src/tools/qureo_auto_solver/`.

لا توجد أدوات KIROYO أو Java أو Python مستقلة في الملفات المرفوعة، لذلك لم يتم اختراع وحدات غير موجودة.

## Architecture

```text
Client / future WISO
        |
        v
Tools Platform API
        |
        +--> SPX Financial Literacy
        |
        +--> Qureo Auto Solver
```

كل Tool معزولة داخل `src/tools/`، والمنطق الأصلي محفوظ قدر الإمكان. الـAPI layer مسؤول عن jobs، request IDs، validation، health checks، وerror sanitization.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
uvicorn src.server.app:app --host 0.0.0.0 --port 8080
```

Health:
`GET /health`

## API

### SPX

`POST /api/tools/sprix/subjects`

```json
{"code":"...", "password":"..."}
```

`POST /api/tools/sprix/solve`

```json
{
  "accounts":[{"code":"...","password":"..."}],
  "subject_id":"7"
}
```

### Qureo

`POST /api/tools/qureo/solve`

```json
{
  "accounts":[{"code":"...","password":"..."}],
  "courses":["Python","JavaScript"]
}
```

Long-running calls return a `request_id`. Query:

`GET /api/jobs/{request_id}`

Stop:

`POST /api/jobs/{request_id}/stop`

Optional `X-Request-ID` makes the request idempotent at the API/job layer for retries that reuse the same ID.

## Environment

See `.env.example`. No real credentials or secrets are committed.

## Railway

Railway uses the included Dockerfile. The container installs Python dependencies and the Playwright-managed Chromium runtime.

- Build: Dockerfile
- Start: `uvicorn src.server.app:app --host 0.0.0.0 --port ${PORT:-8080}`
- Port: Railway-provided `PORT`
- Health: `/health`
- Required runtime ENV: none beyond Railway `PORT`; external URLs are configurable and have non-secret defaults.
- `ALLOWED_ORIGINS` is optional and should contain explicit origins if browser CORS is needed.

## Privacy

This project intentionally contains no analytics, telemetry, session replay, fingerprinting, microphone/camera APIs, screen recording, keystroke logging, clipboard monitoring, or external crash reporting.

Credentials are accepted only as request inputs required by the underlying tools and are not persisted by the API layer. Logs intentionally omit request bodies and solver logs.

The only outbound domains discovered in the source and retained are the service domains required by the two tools:

- `egy.app.spx-learning-square.com`
- `me-portal.qureo.education`
- `me-tp.qureo.education`

## WISO readiness

WISO can later call these endpoints through its backend. WISO remains responsible for identity, authentication, authorization, subscription, payment, wallet, and admin. This project remains responsible for tool execution and external tool APIs.

No WISO code or WISO database was added.
