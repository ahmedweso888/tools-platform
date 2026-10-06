# Tools

## SPX Financial Literacy

Source: uploaded `الثقافة الماليه` project.

Runtime files retained:
- `solver.py`
- `spx_api_bank.json`
- `spx_api_bank_subject3.json`
- `answers_archive.json`
- `answers_archive_subject3.json`

The original SPX base URL is now configurable through `SPX_BASE_URL`.

## Qureo Auto Solver

Source: uploaded `autoqureo_src`.

Runtime files retained:
- `solver.py` (renamed from `auto_solver.py` for consistency)
- `answers.json`

The portal and tool URLs are configurable through:
- `QUREO_PORTAL_LOGIN_URL`
- `QUREO_PORTAL_HOME_URL`
- `QUREO_BASE_URL`

A minimal deployment-only change was made to allow the solver to fall back to Playwright-managed Chromium when system Firefox/Chrome/Edge is unavailable, which is required for Railway Docker.
