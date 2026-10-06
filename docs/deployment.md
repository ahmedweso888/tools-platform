# Deployment

## Railway

1. Push the `tools-platform` root to Git.
2. Create a Railway service from the repository.
3. Railway detects `Dockerfile` and uses `railway.json`.
4. Set `ALLOWED_ORIGINS` only if a browser client needs CORS.
5. Deploy and verify `GET /health`.

The Docker image installs Playwright Chromium with its Linux dependencies.

## Runtime notes

The job store is in memory. A Railway restart clears in-progress job state. The underlying tools themselves keep their answer banks on disk, so this repository does not claim durable distributed resume semantics.

No external database, Redis, queue, or worker service was added.
