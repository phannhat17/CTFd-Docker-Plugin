# Changelog

Notable changes to this plugin, grouped by the problem each one solved. This project follows [Semantic Versioning](https://semver.org/).

## [2.1.0]

A review pass over the whole plugin. Most of this release fixes things that were broken or unsafe, plus a new admin console and an audit trail viewer.

### Security

- Flags are looked up per challenge. The lookup queried by flag hash alone, so a flag generated for one challenge could solve a different challenge.
- Submitting another team's flag no longer bans the flag owner. Reuse is logged and alerted, and banning is opt-in through the new **Auto-ban threshold** setting. The previous behaviour let anyone ban an innocent team on purpose.
- The settings API accepts only a documented allow-list of keys, and validates each value before writing it. It used to persist any key, and it re-ran the SSH setup on every save.
- The config API no longer returns the flag encryption key.
- Removed two cross-site scripting sinks. The flag pattern preview and every rendered connection string now use `textContent` instead of `innerHTML`, so admin-supplied content is never interpreted as markup.
- Flag lookups use a keyed HMAC instead of a bare SHA256, and comparison is constant time.
- SSH connection values are validated before they are written to `~/.ssh`. A newline in the hostname or in the known hosts entry could previously inject additional SSH options.
- Generated flags have a minimum random length of 8, and the alphabet excludes characters that are easy to confuse when copied by hand.

### Added

- A standalone admin console at **Admin, Containers, Console**. It ships its own design, has tabs for instances, settings, cheat logs, the audit trail and import, and does not depend on the CTFd theme.
- An audit trail viewer. The plugin has always written `container_audit_logs`, but there was no way to read it from the UI. It is filterable by event type, severity and search term.
- A paginated cheat log endpoint that resolves team and user names in bulk instead of two queries per row.
- New settings: **Bind challenge ports to**, **Renewal extension**, **Auto-ban threshold**, **Audit retention**, **Traefik entrypoint**, **Use TLS**, and configurable network names.
- A shared flag pattern parser in `utils/flag_pattern.py`, used by the admin form, the importer and the model validation.
- A 30 second expiry sweep that runs alongside Redis, so containers still expire when Redis notifications are unavailable, and a six hour job that prunes old flag attempts.
- An orphaned container reaper that removes containers with no matching live instance row.
- A `docs/` folder with a full guide and screenshots.

### Changed

- Container names include the challenge id, so two challenges with the same name cannot collide.
- Port allocation is randomised, uses an atomic Redis lock, and releases the lock on stop. Ports used to leak until the lock TTL expired.
- Images are pulled explicitly with a long timeout before the container starts, so a missing image produces a clear error instead of a hanging request.
- Subdomain routing no longer reserves host ports, because Traefik reaches the container over the Docker network.
- Renewing adds the extension on top of the current expiry. It used to reset the expiry to `now + extension`, which could shorten a container's life.
- Background jobs coalesce and run on a 30 second cadence. They are safe to run from any thread.
- Stopped, solved and errored instance records are removed after the retention period instead of accumulating.
- Audit details are sanitised before they are written to the JSON column.
- `requirements.txt` is version bounded and complete, and `docker/` ships a Dockerfile with a constraints file so the dependencies install into the CTFd image without breaking CTFd's own pins.

### Fixed

- The expiry sweep crashed when it ran outside a request context. Every scheduled run raised, so expired containers stayed alive and their instances were marked `error`.
- The cleanup job used `signal.alarm`, which only works on the main thread, so it failed in every worker.
- Released ports were never actually released. The lock key was left to expire on its own, so reuse was unreliable.
- CSV import did not work. The endpoint only accepted Excel while the UI, the README and the sample file were all CSV.
- Deleting a challenge left its containers running, with no row left to manage them.
- A 409 conflict from the Docker daemon, which happens when `auto_remove` removes a container before the plugin does, surfaced as an `ObjectDeletedError` and marked the instance `error`.
- The Redis expiration service assumed a Redis backend existed, hardcoded database 0, required `CONFIG SET`, and never reconnected after an error.
- Extending the expiry silently did nothing when the Redis key was missing.
- The instance panel in the challenge view never rendered. CTFd wraps the `connection_info` block in `{% if challenge.connection_info %}`, and the plugin never populated that column.
- The challenge modal kept showing the previous challenge's connection details, because CTFd reuses a single modal element. The panel is now tied to the challenge it belongs to.
- A challenge created with Standard scoring was stored with a decay of 20 from the column default, so the first solve recalculated its value as if it were dynamic and jumped it to the initial value.
- The anti-cheat service returned `is_cheating` inverted: true when nothing was banned and false when a ban was applied.
- The instance list issued one query per row, and the statistics ran five separate counts. Both are now single queries.
- Removed a duplicate import and a duplicate global, replaced deprecated `Query.get()` calls, and corrected two SQLAlchemy API calls that would raise on first use.

### Upgrade notes

**Auto-banning is off after upgrading.** The old behaviour banned both the submitter and the flag owner on the first reuse detection. That let anyone ban an innocent team by submitting their flag. Detection and logging still happen, and the Discord alert still fires. To restore automatic banning, set **Auto-ban threshold** to 1 or more. A threshold above 1 is recommended, since a threshold of 1 is exactly what an attacker can trigger deliberately.

**Challenges created before this release have a decay of 20**, which the old column default supplied. Those challenges still recalculate their value on the next solve. To correct them, either open each challenge in the admin panel and pick **Standard** under Scoring Type, or run:

```sql
-- check which challenges are affected
SELECT c.id, c.name, cc.decay, cc.initial
FROM container_challenge cc JOIN challenges c ON c.id = cc.id
WHERE cc.decay > 0 AND cc.initial IS NOT NULL;

-- turn the standard ones into standard scoring
UPDATE container_challenge SET decay = 0 WHERE decay IS NULL OR decay = 20;
```

Run the first query before the update, in case a challenge really is dynamic with a decay of 20.

**Flag format changed.** Flags no longer carry the per-account fingerprint suffix, and the random alphabet changed. Flags that were already issued stay valid, because validation uses the stored hash. New flags use the new format, so a challenge can hold a mix of both during an event.

**Unknown settings are now rejected.** A script that wrote extra keys through `/admin/containers/api/config` will see them ignored and reported back in the response.

**Dependencies are required.** The plugin imports `docker`, `apscheduler`, `openpyxl` and `paramiko` at load time. They are not part of the stock CTFd image, and bind mounting the plugin does not install them. Build the image with the Dockerfile in `docker/`, or install them into the running container. See [installation.md](installation.md).

## Earlier releases

`v1.1.1` through `v2.0.3` were tagged before this changelog existed. Use `git log v2.0.3` for the history up to that point.
