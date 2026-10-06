# Architecture

The repository is intentionally a single deployable Python application.

- `src/server/`: HTTP API, health checks, job lifecycle and routing.
- `src/tools/sprix_financial_literacy/`: original SPX solver plus its answer banks.
- `src/tools/qureo_auto_solver/`: original Qureo solver plus its answer bank.
- `src/shared/`: only cross-tool runtime configuration.
- `tests/`: smoke tests for the API shell.

The tools are not merged together. The server only orchestrates calls to each tool.

Long-running executions are represented by an in-memory `request_id`. No database or Redis was introduced because the uploaded tools do not require one for their current runtime.
