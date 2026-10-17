# How lightweight Python job runners handle multi-day jobs on one host

Research for [issue #2](https://github.com/tyan001/cate-neuroimaging-pipeline/issues/2), feeding [#3 "Monolith or microservices?"](https://github.com/tyan001/cate-neuroimaging-pipeline/issues/3). This note reports facts. It does not choose an architecture.

Researched 2026-10-17 against: Celery 5.6 docs (latest release v5.6.3), RQ `master` (latest release v2.12; 3.0 unreleased), Huey latest docs (3.4.0), Dramatiq `master` (latest release v2.2.1), arq `main` (v0.28.0), RabbitMQ, Redis, Docker, PostgreSQL and SQLite docs.

## The workload

- A Batch runs for hours to days. `recon-all` takes 8–12 h per Session, and the Sessions in a Batch run in parallel.
- At most 2 Batches run at once. The others wait in a queue.
- One Linux VM with Docker. The host can reboot in the middle of a Batch.
- Each task may start a Docker container (FreeSurfer + FSL image) and report progress to a small Python web app.

The cap of 2 applies to **Batches**, not to tasks. If one task = one Session, the runner's per-worker concurrency setting does not express "2 Batches". The runner needs a group-level limit, or the app must decide when to admit a Batch.

## Celery

**Extra services.** A broker is required. The first-class brokers are RabbitMQ and Redis. Results, including progress state, go to a result backend. That backend can be a SQL database through SQLAlchemy (`result_backend = 'db+scheme://...'`) ([configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html#database-backend-settings)).

**Concurrency cap.** `worker_concurrency` / `--concurrency` sets the number of processes or threads per worker. The default is the number of CPU cores. By default a worker prefetches `worker_prefetch_multiplier` (4) × concurrency messages ([configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-prefetch-multiplier)). For long tasks the docs say "you want the multiplier value to be *one*", together with `task_acks_late = True`. With those settings a worker reserves only as many tasks as it has processes ([optimizing: prefetch limits](https://docs.celeryq.dev/en/stable/userguide/optimizing.html#prefetch-limits)). There is no built-in cap for a group of tasks, such as "2 Batches".

**Very long tasks.**
- Tasks have no time limit by default (`task_time_limit` and `task_soft_time_limit`: "No time limit") ([configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit)).
- By default a message is acked *before* the task runs. With `acks_late` it is acked after the task finishes, and then "the task may be executed multiple times should the worker crash in the middle of execution" ([tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html#Task.acks_late)).
- **Redis broker:** "The default visibility timeout for Redis is 1 hour." "If a task isn't acknowledged within the Visibility Timeout the task will be redelivered to another worker and executed." For tasks longer than that, the docs say to raise the timeout, and they warn that this "is not recommended as it may have negative impact on the reliability" ([Redis broker: visibility timeout](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html#visibility-timeout)). So a 12 h late-acked task needs `visibility_timeout` above 12 h, or it runs again every hour.
- **RabbitMQ broker:** RabbitMQ enforces a delivery acknowledgement timeout (`consumer_timeout`) with a default of 30 minutes. When a delivery is not acked in time, the channel is closed with `PRECONDITION_FAILED` and its deliveries are requeued. The timeout can be raised in `rabbitmq.conf`, per queue by policy (`consumer-timeout`), or by queue argument (`x-consumer-timeout`). Disabling it is possible but not recommended ([RabbitMQ consumers: acknowledgement timeout](https://www.rabbitmq.com/docs/consumers#acknowledgement-timeout)).

**Recovery after a worker or host restart.**
- With early ack (the default), a task that is running when the worker dies is not redelivered.
- With `acks_late`, Celery requeues unacked messages at a normal worker shutdown. After a power failure or forced kill, a Redis-brokered task waits until the visibility timeout expires ([Redis broker](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html#visibility-timeout)). On RabbitMQ, "any delivery (message) that was not acked is automatically requeued when the channel (or connection) on which the delivery happened is closed" ([RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms#automatic-requeueing)).
- If the child process is killed by a signal, an OOM kill or `sys.exit()`, the message is acked even with `acks_late`, unless `task_reject_on_worker_lost` is enabled. The docs warn that this setting "can cause message loops" ([tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-reject-on-worker-lost)).
- With a Redis broker, queued messages survive a host reboot only if Redis persistence is configured. RDB snapshots can lose "the latest minutes of data". AOF with the default `appendfsync everysec` loses at most about 1 second ([Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)).

**Progress reporting.** Built in. A bound task calls `self.update_state(state='PROGRESS', meta={'current': i, 'total': n})`, and the docs say the metadata "can then be used to create progress bars" ([tasks: custom states](https://docs.celeryq.dev/en/stable/userguide/tasks.html#custom-states)). With `task_track_started`, the state also records the worker's host name and PID ([configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-track-started)).

## RQ (Redis Queue)

**Extra services.** Redis only. Jobs, results, registries and heartbeats are all stored in Redis.

**Concurrency cap.** "Each worker will process a single job at a time". To run jobs concurrently, "simply start more workers" ([workers](https://python-rq.org/docs/workers/)). `rq worker-pool -n N` runs N workers from one command (default 2). The number of workers is therefore a hard cap on running jobs. Each job runs in a forked "work horse" child process. RQ 3.0, which is **unreleased**, adds concurrency rate limits per key: `queue.enqueue(func, rate_limit=RateLimit(...))`. A job without a free slot waits in a `rate_limited` status ([CHANGES.md](https://github.com/rq/rq/blob/master/CHANGES.md), [`queue.py`](https://github.com/rq/rq/blob/master/rq/queue.py)).

**Very long tasks.**
- The default job timeout is 180 s (`Queue.DEFAULT_TIMEOUT = 180`). `-1` means no timeout, and `0` is rejected ([`queue.py`](https://github.com/rq/rq/blob/master/rq/queue.py)). Every 12 h job must therefore set `job_timeout`.
- RQ has no visibility timeout. While the work horse runs, the parent worker refreshes the heartbeats of the worker, the job and the execution every `job_monitoring_interval` (default 30 s, TTL = interval + 60 s) ([`worker/base.py`](https://github.com/rq/rq/blob/master/rq/worker/base.py), [`defaults.py`](https://github.com/rq/rq/blob/master/rq/defaults.py)). `SimpleWorker`, which does not fork, "does not provide periodic heartbeats during job execution" ([workers](https://python-rq.org/docs/workers/)).

**Recovery after a worker or host restart.**
- On SIGINT or SIGTERM, a worker waits for the current job to finish. A second signal sends SIGKILL to the work horse ([workers](https://python-rq.org/docs/workers/)).
- When a worker dies in the middle of a job, its entry in `StartedJobRegistry` expires once heartbeats stop. Another worker's maintenance task then finds the job, which runs every `--maintenance-interval` (default 600 s). The job is retried if it has `retries_left`. Otherwise it is moved to `FailedJobRegistry` with `AbandonedJobError` ([exceptions](https://python-rq.org/docs/exceptions/), [`registry.py` `StartedJobRegistry.cleanup`](https://github.com/rq/rq/blob/master/rq/registry.py)). Automatic re-run therefore depends on `Retry(max=...)`.
- Whether queued jobs survive a reboot depends on Redis persistence, as with Celery on Redis.

**Progress reporting.** Store data in `job.meta` and call `job.save_meta()`. The web app reads it with `job.get_meta()` ([jobs](https://python-rq.org/docs/jobs/)).

## Huey

**Extra services.** None if you use `SqliteHuey`, which needs only the standard-library `sqlite3` module and a file. `RedisHuey` needs Redis, and `PostgresHuey` needs PostgreSQL ([API](https://huey.readthedocs.io/en/latest/api.html)).

**Concurrency cap.** `-w` sets the number of workers (default 1), and `-k` sets the worker type: thread (the default), process or greenlet ([consumer](https://huey.readthedocs.io/en/latest/consumer.html)). So `-w 2` caps running tasks at 2. `lock_task` gives mutual exclusion per lock name, not a count-based limit. `rate_limit` is a fixed-window rate limiter, not a concurrency limit ([API](https://huey.readthedocs.io/en/latest/api.html)).

**Very long tasks.** Huey has no acknowledgement, so there is no visibility timeout or redelivery to manage while a task runs.

**Recovery after a worker or host restart.** "Huey does not guarantee at-least-once delivery of messages, and does not do acknowledgement of completed tasks." "If you terminate the consumer without letting it finish any currently-executing tasks, those tasks will be lost." `SIGNAL_INTERRUPTED` reports the loss ([consumer: shutdown](https://huey.readthedocs.io/en/latest/consumer.html)). SIGINT lets running tasks finish and SIGTERM interrupts them. Health checks (`-c`, default 10 s) restart dead worker threads or processes. `-f` clears task locks left behind by an abrupt kill ([consumer](https://huey.readthedocs.io/en/latest/consumer.html)). After a host reboot, a task that was running does not come back unless the application re-enqueues it.

**Progress reporting.** No dedicated API. A task can write with `huey.put(key, data)`, and the app can read with `huey.get(key, peek=True)`. Reads are destructive by default ([API](https://huey.readthedocs.io/en/latest/api.html)).

## Dramatiq

**Extra services.** RabbitMQ or Redis as the broker. Result storage and `ConcurrentRateLimiter` need a backend; the docs' example uses `RedisBackend` ([cookbook: rate limiting](https://dramatiq.io/cookbook.html#rate-limiting)).

**Concurrency cap.** `--processes` defaults to the CPU count and `--threads` to 8 per process ([`cli.py`](https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/cli.py)). A global cap across processes uses `ConcurrentRateLimiter(backend, key, limit=N)`. When the limiter is full, the actor raises an exception and is retried with backoff, unless you pass `raise_on_failure=False` ([cookbook](https://dramatiq.io/cookbook.html#rate-limiting)).

**Very long tasks.**
- The `TimeLimit` middleware cancels actors after **10 minutes by default** (600,000 ms). Set `time_limit=float("inf")` to disable it. It works by raising an async exception in the worker thread, so it "can't cancel system calls" ([`middleware/time_limit.py`](https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/middleware/time_limit.py)).
- Retries: `max_retries` defaults to 20, with backoff from 15 s up to 7 days ([`middleware/retries.py`](https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/middleware/retries.py)).
- **Redis broker:** Dramatiq has no visibility timeout. A worker counts as dead when no heartbeat arrives for `heartbeat_timeout` (default 60 s). Maintenance runs on about 0.1% of broker commands and moves the unacked messages of dead workers back to their queues ([`brokers/redis.py`](https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/brokers/redis.py), [`brokers/redis/dispatch.lua`](https://github.com/Bogdanp/dramatiq/blob/master/dramatiq/brokers/redis/dispatch.lua)). The heartbeat is written only as part of a broker command (`zadd` in `dispatch.lua`). The consumer stops fetching while its prefetch buffer is full (`RedisConsumer.__next__`). Open issue [#692](https://github.com/Bogdanp/dramatiq/issues/692) reports long-running tasks being requeued, and run twice, with no worker failure.
- **RabbitMQ broker:** the RabbitMQ `consumer_timeout` described under Celery applies. Inference, not checked in Dramatiq's docs: because Dramatiq acks after processing, a 12 h actor needs that timeout raised.

**Recovery after a worker or host restart.** Messages are acked after processing. After a crash, unacked messages are requeued: on Redis by the heartbeat maintenance above, and on RabbitMQ when the channel closes ([RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms#automatic-requeueing)). Redis persistence applies as for Celery and RQ.

**Progress reporting.** No built-in progress API. The `Results` middleware stores only return values, and they expire after 10 minutes by default ([cookbook: results](https://dramatiq.io/cookbook.html#results)). Progress must go to the app's own store.

## arq

**Status.** The README says: "**In maintenance only mode**: arq is in maintenance only mode, see [#510](https://github.com/python-arq/arq/issues/510)" ([README](https://github.com/python-arq/arq)).

**Extra services.** Redis. Jobs, results and health checks are stored in Redis ([docs](https://arq-docs.helpmanual.io/)).

**Concurrency cap.** `max_jobs` sets the number of concurrent jobs per worker (default 10) ([docs](https://arq-docs.helpmanual.io/)). arq is built on asyncio, so jobs are coroutines. Inference: blocking calls, such as the synchronous Docker SDK, must be moved off the event loop.

**Very long tasks.**
- `job_timeout` defaults to 300 s.
- When a worker picks up a job, it sets an "in progress" key with a TTL of the longest function timeout + 10 s. Other workers skip a job whose key exists ([`worker.py`](https://github.com/python-arq/arq/blob/main/arq/worker.py)). A 12 h timeout therefore means a 12 h lock.

**Recovery after a worker or host restart.** In arq's "pessimistic execution", "jobs aren't removed from the queue until they've either succeeded or failed". On shutdown, a running job "will be cancelled immediately and will remain in the queue to be run again" ([docs](https://arq-docs.helpmanual.io/)). After a hard crash, the in-progress key stays until its TTL expires, so another worker cannot start the job until then (inference from `worker.py`). `max_tries` defaults to 5.

**Progress reporting.** No progress API. `Job.status()` returns `deferred`, `queued`, `in_progress`, `complete` or `not_found` ([docs](https://arq-docs.helpmanual.io/)).

## Plain database-polling worker

You write the worker yourself: a loop that claims a row from a `jobs` table in the app's own database, runs the work, and updates the row.

**Extra services.** None beyond the database the web app already uses.

**Claiming work.**
- **PostgreSQL:** `SELECT ... FOR UPDATE SKIP LOCKED` "can be used to avoid lock contention with multiple consumers accessing a queue-like table" ([PostgreSQL SELECT: locking clause](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)).
- **SQLite:** has no `SKIP LOCKED`. It "will only allow one writer at any instant in time", and "writers queue up" ([when to use SQLite](https://www.sqlite.org/whentouse.html)). A single worker process can claim a row atomically with `UPDATE ... RETURNING`, which SQLite has supported since 3.35.0 ([RETURNING](https://www.sqlite.org/lang_returning.html)). SQLite fits "device-local storage with low writer concurrency".

**Concurrency cap, long tasks, recovery, progress.** None of these are built in. Each is a query over your own schema, for example "count the Batches in state `running`; admit the next one only if the count is below 2". There is no broker timeout, so a 12 h or multi-day job needs no special settings. You design recovery yourself: at startup, find rows still marked `running` from before the reboot, then decide whether to resume or re-run. Progress is a column or table that the web app already reads.

## Starting Docker containers from a task (applies to every option)

- With the Docker SDK for Python, `client.containers.run(image, ..., detach=True, name=..., labels={...}, volumes=..., user=...)` returns a `Container` right away. `container.wait()` returns a dict with the exit code under `StatusCode`. `container.logs(stream=True, follow=True)` returns a blocking generator. `client.containers.list(filters={'label': 'key=value'})` and `client.containers.get(name)` find containers again later ([docker-py containers](https://docker-py.readthedocs.io/en/stable/containers.html)).
- The Docker daemon owns the container, not the worker. If the worker process dies, a detached container keeps running, and a restarted worker can find it again by name or label. The runner's own retry or redelivery cannot see this. A naive re-run may start a second container for the same Session.
- After a **daemon stop or host reboot**: "By default, when the Docker daemon terminates, it shuts down running containers" ([live restore](https://docs.docker.com/engine/daemon/live-restore/)). Live restore keeps containers running only across a daemon restart, not a host reboot. The restart policies `always` and `unless-stopped` restart containers when the daemon comes back. `on-failure` does not ([restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/)). A restart policy would restart the container command from the beginning, with no task supervising it. Whether a partly finished `recon-all` can resume was not researched here.

## Comparison

| | Extra service | Concurrency cap | Default limit that a 12 h task hits | Task running at crash/reboot | Progress to web app |
|---|---|---|---|---|---|
| **Celery** | Redis or RabbitMQ (+ optional SQL result backend) | `--concurrency` per worker; no group cap | Redis visibility timeout 1 h (with `acks_late`); RabbitMQ `consumer_timeout` 30 min | Early ack (default): lost. `acks_late`: redelivered after the visibility timeout (Redis) or on channel close (RabbitMQ). OOM/kill: acked unless `task_reject_on_worker_lost` | Built in: `update_state` + custom states |
| **RQ** | Redis | 1 job per worker; cap = number of workers; per-key limits only in unreleased 3.0 | Job timeout 180 s (set `-1`) | Detected after heartbeat TTL + maintenance (≤ 10 min); retried if `Retry` is set, else failed with `AbandonedJobError` | `job.meta` + `save_meta()` |
| **Huey** | None (`SqliteHuey`) or Redis/Postgres | `-w N` | None | **Lost**: no ack, no at-least-once delivery | `put`/`get` key-value store only |
| **Dramatiq** | Redis or RabbitMQ (+ backend for rate limiter/results) | processes × threads; `ConcurrentRateLimiter` for a global cap | `TimeLimit` 10 min; RabbitMQ `consumer_timeout` 30 min | Requeued (Redis heartbeat maintenance / RabbitMQ channel close); open report (#692) of duplicate runs for long tasks on Redis | None built in |
| **arq** (maintenance-only) | Redis | `max_jobs` per worker (default 10) | `job_timeout` 300 s | Stays queued; blocked until the in-progress key expires (timeout + 10 s) | Status only |
| **DB polling** | None (the app's SQLite/Postgres) | Whatever you query (can be "≤ 2 running Batches" directly) | None | Whatever you write; the job's state is a row the app already owns | A column/table the app already reads |

## Which options fit this workload, and why

These points follow from the facts above. Choosing among the options belongs to #3.

- **No extra service, survives reboot by design:** a database-polling worker, or Huey with `SqliteHuey`. Huey loses any task that is running at a crash or reboot, so with either option the app's own state must record which Sessions were running and re-enqueue them. Huey then adds little beyond the polling loop.
- **Batch-level cap of 2:** no runner here has a built-in "N groups" limit, except a custom query in a DB-polling worker. The others reach it in one of two ways. Either a Batch is one long task and the worker count is 2 (Celery `--concurrency 2`, `rq worker-pool -n 2`, Huey `-w 2`), or the app admits Batches and the runner only runs Session tasks. Dramatiq's `ConcurrentRateLimiter` and RQ 3.0's `RateLimit` give counted caps, but each needs Redis.
- **Multi-day tasks fight the broker-based runners' defaults:** Celery on Redis (1 h visibility timeout) or RabbitMQ (30 min `consumer_timeout`), Dramatiq (10 min `TimeLimit`, plus #692 on Redis), arq (300 s, maintenance-only) and RQ (180 s). Each default can be raised. Of these, RQ's heartbeat model needs only `job_timeout=-1` and keeps the time between a crash and recovery short.
- **Docker as the unit of work:** every option can start detached containers through the Docker SDK. The container outlives a dead worker but not a host reboot. Recovery therefore depends on reconciling containers (by label) with the app's job records, whichever runner is chosen. That favors designs where the app's database, not the broker, holds the authoritative Session state.
- **Progress to the web app:** only Celery (`update_state`) and RQ (`job.meta`) have a progress channel. With every other option, and in practice with these two as well if the web app needs a database anyway, progress is written to the app's database.

## Open questions not resolved here

- Whether `recon-all` can resume a partly finished subject directory after a reboot, or must restart it from scratch. This decides how much recovery logic is worth building.
- Whether the web app's database will be SQLite or PostgreSQL. This changes how a polling worker claims jobs (`SKIP LOCKED` or a single claiming process).
