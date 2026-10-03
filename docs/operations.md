---
title: Operations
description: "Background jobs, expiry, retention, recovery and monitoring."
---

# Operations

Day to day behaviour of the plugin: what runs in the background, what the database holds, and how to recover from common situations.

## Background jobs

Three jobs run inside the CTFd process through APScheduler.

| Job | Interval | What it does |
| --- | --- | --- |
| Expiry sweep | 30 seconds | Stops instances whose expiry has passed |
| Retention job | 1 hour | Deletes old instance records and reaps orphaned containers |
| Attempt prune | 6 hours | Trims the oldest flag attempts |

Jobs coalesce and are limited to one instance each, so a slow run does not pile up. They can be disabled with the `background_jobs_enabled` setting, which is useful during a database migration or debugging.

In a deployment with more than one worker, each worker runs its own scheduler. The jobs are written to be idempotent, so duplicate runs are harmless. The first worker to reach an expired instance stops it, and the others see the status already changed and skip it.

## How expiry works

Two mechanisms run in parallel, and either one is enough.

**Redis keyspace notifications.** When an instance starts, the plugin writes a key `container:expire:<uuid>` with a TTL equal to the remaining lifetime. When the key expires, Redis publishes an event, the plugin's listener receives it, and the container is stopped at that moment.

**Periodic sweep.** Every 30 seconds the plugin looks for instances whose `expires_at` has passed and stops them. This covers deployments without Redis, and the case where a Redis event was lost.

Redis is worth configuring because it gives second accuracy. The sweep is the safety net.

Renewals extend both: the Redis key TTL is extended by the same amount, and `expires_at` is moved forward.

## What happens when an instance stops

Stopping an instance does all of the following in order:

1. Sets the status to `stopping`.
2. Cancels the Redis expiry key.
3. Asks Docker to stop and remove the container.
4. Releases the host ports back to the pool.
5. Sets the final status to `solved`, `stopped`, or leaves `error`.
6. Writes an audit entry.

Ports are released in step 4 but the instance row keeps the port numbers as a history. Only rows in `running`, `provisioning`, or `stopping` are treated as holding a port, so a stopped row does not block reuse.

## Retention

Instance records are kept for `audit_retention_days`, 7 by default, and then deleted along with their invalidated flag records. The retention job also reports containers that exist in Docker but have no matching live row, and removes them.

This is what keeps the tables from growing without limit across an event.

## Database tables

| Table | Rows |
| --- | --- |
| `container_challenge` | One per container challenge |
| `container_instances` | One per spawned container, kept as history |
| `container_flags` | One per generated flag while it is relevant |
| `container_flag_attempts` | One per flag submission |
| `container_audit_logs` | One per lifecycle event |
| `container_config` | Plugin settings |

Useful queries:

```sql
-- instances currently holding a port
SELECT id, uuid, challenge_id, account_id, connection_port, expires_at
FROM container_instances
WHERE status IN ('running', 'provisioning', 'stopping');

-- reuse detections in the last day
SELECT challenge_id, account_id, flag_owner_account_id, ip_address, timestamp
FROM container_flag_attempts
WHERE is_cheating = 1 AND timestamp > NOW() - INTERVAL 1 DAY;

-- how many instances each status has
SELECT status, COUNT(*) FROM container_instances GROUP BY status;
```

## Finding the plugin's containers

Every container the plugin starts carries `ctfd.managed=true`:

```sh
# what is running now
docker ps --filter label=ctfd.managed=true

# including stopped ones
docker ps -a --filter label=ctfd.managed=true

# which instance a container belongs to
docker inspect <container> --format '{{index .Config.Labels "ctfd.instance_uuid"}}'
```

## Recovering from an inconsistent state

### A container exists but there is no instance row

This happens if CTFd was killed between starting the container and committing the row. Run **Prune old records** on the Instances tab, or wait for the hourly job. Orphaned containers are found by comparing Docker's labels with the live rows.

### An instance row says `running` but the container is gone

The player sees a dead link. Use **Delete** on the row. The next **Fetch Instance** starts a fresh container.

### An instance is stuck in `provisioning`

This means the plugin crashed or was restarted mid-provision, or an image pull is still running. The expiry sweep picks it up once its expiry passes. To clear it immediately, use **Stop** or **Delete** on the row, or **Clean expired**.

### Every new instance returns a port error

The port range is exhausted. Check **Free ports** on the Instances tab. Stopped instances do not hold ports, so a low number means many containers really are running, or rows are stuck in `running` while their containers are gone. Clean up the stale rows, or widen the port range in Settings.

### Docker was restarted

The plugin caches its Docker client. If the daemon restarts and the client goes stale, save a settings change on the Settings tab, which forces a reconnect, or restart CTFd.

## Monitoring

The Instances tab is enough for a single host event. For anything larger, watch:

- **Free ports** on the Instances tab, or `/admin/containers/api/stats`.
- **Running** and **Error** counts.
- The Docker panel's running container count.
- `docker system df` on the host, since images accumulate.

The stats endpoint returns JSON and can be polled by an external monitor:

```sh
curl -s -b cookies.txt https://ctf.example.com/admin/containers/api/stats
```

## Scaling notes

The plugin controls one Docker daemon, reached over the local socket or over SSH. It does not implement a scheduler across several hosts, and it does not partition port ranges per host. Running several hosts means running several CTFd instances, or accepting that a single daemon is the bottleneck.

For one host with a few hundred simultaneous containers, the current design is fine. The port range is the practical limit: a range of 1000 ports supports 1000 simultaneous published ports, and a multi port challenge consumes one per port.

## Running the test suites

Two suites ship in the development workspace, outside the plugin folder.

```sh
# in-process, uses a fake Docker client, 19 checks
python3 harness/run_tests.py

# against a live stack with a real Docker daemon, 38 checks
docker compose cp harness/e2e_v2.py ctfd:/tmp/e2e_v2.py
docker compose exec -T ctfd /opt/venv/bin/python /tmp/e2e_v2.py

# browser checks
python3 harness/ui_console_check.py
python3 harness/ui_confirm_check.py
python3 harness/ui_modal_switch_check.py
```

`harness/capture_docs.py` regenerates every screenshot in this folder.
