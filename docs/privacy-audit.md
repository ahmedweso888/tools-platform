# Privacy Audit

Audit scope: uploaded source code, runtime configuration, dependencies, build/deployment files, browser/client code, and discovered outbound URLs.

| Area | Result |
|---|---|
| Tracking | NONE FOUND |
| Analytics | NONE FOUND |
| Telemetry | NONE FOUND |
| Session Recording | NONE FOUND |
| Screen Recording | NONE FOUND |
| Microphone Listening | NONE FOUND |
| Camera Access | NONE FOUND |
| Keyboard Logging | NONE FOUND |
| Fingerprinting | NONE FOUND |
| Hidden Monitoring | NONE FOUND |
| Unauthorized Third-Party Sharing | NONE FOUND |

## Findings

- The original local web UI contained a clipboard **paste handler** only to parse user-pasted account lines. It was removed from the backend deployment because the UI is not required on Railway.
- No `sendBeacon`, analytics SDK, telemetry SDK, session replay, microphone/camera APIs, keyboard logging, or fingerprinting implementation was found in the retained runtime.
- `fetch`/HTTP calls in the retained engines are directed only to the external service domains required by those engines.
- Build artifacts, executables, local startup logs, desktop UI assets, `__pycache__`, and generated PyInstaller directories were excluded from the deployment project.
- No real secrets were found in source constants. The original Qureo desktop app had a hard-coded local access username for its desktop lock; that desktop lock is not part of the Railway backend and was not carried into the backend.

## Network allowlist discovered

- `https://egy.app.spx-learning-square.com`
- `https://me-portal.qureo.education`
- `https://me-tp.qureo.education`

No analytics or telemetry destination was discovered.
