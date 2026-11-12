# Production Architecture (Phase 6)

Phase 6 turns the single-process demo into a service that can survive restarts, enforce identity, and
run behind controlled network egress. This document describes the **target production topology** and which
parts were actually exercised locally. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the
verification status of each item.

## Topology

```
                Internet
                   │ 443 (TLS)
              ┌────▼─────┐
              │  nginx   │  security headers, edge rate limits, /metrics + /health/details blocked
              └─┬──────┬─┘
        edge net│      │edge net
         ┌──────▼──┐ ┌─▼────────────────────────────────────────┐
         │frontend │ │ api (FastAPI)                             │
         │Next.js  │ │  • REST + WebSocket                       │
         └─────────┘ │  • planning queue (in-process workers)    │
                     │  • execution worker (Redis queue consumer)│
                     │  • headless Chromium (child processes)    │
                     └──┬─────────────┬─────────────────┬────────┘
              internal  │             │ internal        │ egress net (internal: true)
            ┌───────────▼──┐  ┌───────▼──────┐   ┌──────▼──────┐
            │ PostgreSQL 16│  │  Redis 7     │   │ squid egress │──► internet (web ports only,
            └──────────────┘  └──────────────┘   └─────────────┘     private/metadata ranges denied)
```

* `internal` and `egress` are Docker networks with `internal: true`: the api container has **no direct route to
  the internet**. Chromium (`launch(proxy=…)`) and the file downloader (httpx `proxy=`) are configured to use
  `EGRESS_PROXY_URL`; anything that ignores the proxy simply cannot connect.
* Only nginx publishes ports. Prometheus (optional profile) scrapes the api on the private network with a bearer token.

## Process model

| Component | Where it runs | Notes |
|---|---|---|
| HTTP/WS API | `api` container (uvicorn) | Stateless apart from caches; DB is authoritative. |
| Planning workers | in the api process (`PlannerQueue`) | Bounded queue; restart re-plans interrupted planning once. |
| Execution worker | in the api process (`QueueWorker` over `RedisJobQueue`) | At-least-once delivery + execution journal. |
| Chromium | child processes of the api | Isolated per session (fresh context), proxy enforced. |
| Recovery | api startup, after queues start | See [RESILIENCE_AND_RECOVERY.md](RESILIENCE_AND_RECOVERY.md). |

**Not implemented:** a separate browser-worker container. Chromium runs inside the api container, which is
hardened (non-root, `cap_drop: ALL`, `no-new-privileges`, read-only root, memory/pid limits) but a compromise of
Chromium would share the api's memory space and DB credentials. Splitting the worker out is the main open
architectural item (see [SECURITY_THREAT_MODEL.md](SECURITY_THREAT_MODEL.md)).

## Single API instance

Redis-backed locks, rate limits and the job queue were designed so several api replicas *could* run, but
WebSocket telemetry fan-out is in-process (`WebSocketManager`). Running more than one replica would deliver a
task's events only to sockets connected to the replica executing it. **Production supports one api replica**
until a Redis pub/sub fan-out is added.

## Startup sequence

1. Settings validation (`_validate_production`) — refuses SQLite, disabled auth, missing Redis, missing egress
   proxy, demo endpoints, insecure cookies, persisted browser sessions.
2. `container.startup()` — schema check (`alembic upgrade head` must already have run; the one-shot `migrate`
   service does it), bootstrap OWNER if configured.
3. Sweeper, planning queue, execution queue start.
4. `container.run_recovery()` — reconcile persisted state (never resumes a sensitive action).
5. Traffic is served; `/health/ready` reports database, Redis, planner and configuration.

## Configuration

All tunables are typed settings in `backend/app/config.py`. The production template is
`deployment/.env.production.example`. See [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).
