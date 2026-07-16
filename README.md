# Hydra

Hydra is a small, capacity-aware edge batch runner. A Scheduler persists typed
jobs, a Coordinator leases them to available Workers, and Workers run only the
allowlisted job types they understand. It is designed for trusted fleets of
remote machines or pods—not arbitrary shell execution.

## What it does now

- Dispatches immediately when a due task is scheduled, with a one-second scan
  as recovery for delayed tasks and notification failures.
- Tracks each worker's declared concurrency and will not lease more work than
  it can accept.
- Persists task state, attempts, assigned worker, and lease expiry in
  PostgreSQL. Failed work retries up to `max_attempts` rather than disappearing.
- Runs a constrained Raspberry Pi Zero W simulation through a Compose overlay:
  ARMv6, one CPU, and 512 MiB RAM per worker.

The coordinator is intentionally single-instance. For high availability or a
large untrusted multi-tenant queue, use a mature queue/Kubernetes Job system.

## Run locally

Create `.env` from the example:

```bash
cp .env.example .env
docker compose up --build --scale worker=3
```

The local services are exposed at Scheduler `http://localhost:5000` and
Coordinator `http://localhost:5001`.

### Raspberry Pi Zero W distributed test

Run ten ARMv6 workers, each capped at one CPU and 512 MiB:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.pi-zero-w.yml \
  up --build --scale worker=10
```

The limits and ARMv6 instruction set are real Docker constraints. Wall-clock
speed still depends on the local host and its emulator.

## Schedule a job

`POST /schedule` accepts a typed job rather than a raw shell command. Every
job needs `scheduled_at` in ISO 8601 form; `max_attempts` defaults to `3`.

```bash
curl -X POST http://localhost:5000/schedule \
  -H 'Content-Type: application/json' \
  -d '{
    "job_type": "sleep",
    "payload": {"duration_seconds": 2},
    "scheduled_at": "2026-07-17T12:00:00",
    "max_attempts": 3
  }'
```

Available built-in jobs are:

| Job type | Payload | Purpose |
| --- | --- | --- |
| `echo` | `{"message":"..."}` | Safe connectivity and dispatch check. |
| `sleep` | `{"duration_seconds":0..300}` | Controlled parallelism and timing test. |
| `sha256` | `{"path":"relative/path"}` | Hash a file below the worker's `HYDRA_WORKSPACE` (`/work` by default). |

Workers reject unknown job types and paths outside their workspace. Add a new
job type in `src/worker/worker.go` when a fleet needs a new trusted operation.

Inspect task state with:

```bash
curl http://localhost:5000/schedule/<task-id>
```

## Architecture

```text
Scheduler --persist + notify--> Coordinator --lease--> available Worker
    |                            |                       |
PostgreSQL <---------------------+<------ status ---------+
```

Workers register their IP, port, and `WORKER_MAX_CONCURRENCY`. The coordinator
round-robins only across workers whose in-flight leases are below that limit.
A completed job releases the worker; a failed or expired lease is retried until
its attempt budget is exhausted.

## Verification

The Compose `tests` service runs the unit suite:

```bash
docker compose run --rm tests
```

The official Raspberry Pi profile test ran 20 two-second jobs on ten workers:
all 20 completed, all 10 workers were used, and the two waves took 4.68 seconds.
An invalid workspace job retried twice and reached a persisted `failed` state.

## Security notes

Hydra currently trusts the network between Scheduler, Coordinator, and Workers.
Use a private network, service authentication, and TLS/mTLS before exposing it
outside a controlled environment. The API deliberately does not execute raw
shell commands.
