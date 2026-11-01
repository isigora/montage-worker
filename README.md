# montage-worker

Runs [OpenMontage](https://github.com/calesthio/OpenMontage) productions headlessly for the yt-dub web app.
A Claude agent (Claude Agent SDK) drives the OpenMontage pipeline inside this container; the worker pauses at
every approval gate and resumes the same agent session when the app approves or replies.

- OpenMontage is cloned at a pinned commit during the Docker build (see `Dockerfile`). No changes are made to it.
- Documentary: free path only (open archives, local Piper TTS). Cinematic: fal.ai generation within a per-job media budget.
- Internal service: reachable only on the Railway private network, and every API call needs the `X-Worker-Secret` header.

## Environment

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key for the agent |
| `WORKER_SECRET` | Shared secret; yt-dub sends it as `X-Worker-Secret` |
| `MONTAGE_MODEL` | Model for the agent (default `claude-sonnet-5-5`) |
| `JOB_BUDGET_USD` | Claude spend cap per documentary video (default `3`) |
| `CINEMATIC_CLAUDE_BUDGET_USD` | Claude spend cap per cinematic video (default `5`) |
| `FAL_KEY` | fal.ai key for image/video generation (cinematic only) |
| `MAX_MEDIA_BUDGET_USD` | Upper bound on a job's media budget (default `15`) |
| `DATA_DIR` | Persistent volume (default `/data`): jobs, projects, agent sessions |

## API

| Method | Path | Does |
| --- | --- | --- |
| POST | `/jobs` | Start: `{topic, pipeline, duration_sec, language, owner}` |
| GET | `/jobs?owner=` | List jobs |
| GET | `/jobs/{id}` | Status, current gate, agent message, cost, file list |
| POST | `/jobs/{id}/approve` | Approve the current gate and continue |
| POST | `/jobs/{id}/reply` | Send a revision request or answer: `{text}` |
| POST | `/jobs/{id}/cancel` | Cancel |
| DELETE | `/jobs/{id}` | Delete job and its files |
| GET | `/jobs/{id}/files/{path}` | Download an artifact, e.g. `renders/final.mp4` |
| GET | `/health` | Health check (no auth) |

Job status: `queued` → `running` → `waiting` (gate or question) → … → `done` | `failed` | `cancelled`.

## License

AGPL-3.0, the same as OpenMontage. See `LICENSE`.
