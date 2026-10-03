# Changelog

Every change to this plugin, grouped by the problem it solved.

The "Unreleased" section was produced during a full review of the plugin. Each entry names the symptom that was fixed, so it is also useful as a list of things to check if you are upgrading from an older copy.

## Unreleased

- **Fix**: flags are looked up per challenge, so a flag generated for one challenge can no longer solve another one.
- **Fix**: submitting somebody else's flag no longer auto-bans the innocent owner. Reuse is logged and alerted; banning is opt-in via *Auto-ban Threshold*.
- **Fix**: renewing adds the extension on top of the current expiry instead of resetting it (which could shorten a container's life).
- **Fix**: the background expiry sweep no longer crashes when it runs outside a request context (containers previously stayed alive and were marked `error`).
- **Fix**: expired containers are stopped and their host ports are actually released (Redis locks are deleted and become reusable immediately).
- **Fix**: CSV import works. The endpoint previously only accepted Excel while the UI, the README and the sample file were CSV.
- **Fix**: deleting a challenge now stops its containers.
- **Fix**: no more `ObjectDeletedError`/409 races when the daemon removes a container before the plugin does.
- **Fix**: the settings API accepts only a validated allow-list of keys instead of persisting arbitrary configuration and re-running the SSH setup.
- **Fix**: the config API no longer exposes the flag encryption key.
- **Fix**: XSS in the flag-pattern preview and in every rendered connection string (all DOM writes now use `textContent`).
- **Fix**: Redis integration no longer assumes a Redis backend exists, uses the configured database index, does not require `CONFIG SET`, and reconnects.
- **Fix**: `extend_expiration` re-creates the key when it is missing instead of silently doing nothing.
- **Fix**: admin dashboard queries are eager-loaded, paginate without `error_out`, and stats use one grouped query instead of one per status.
- **Change**: images are pulled explicitly with a long timeout before `run`, so a missing image produces a clear error instead of a hanging request.
- **Change**: containers are named `<challenge>-<id>_<account>` so two challenges with the same name cannot collide.
- **Change**: flags use a keyed HMAC, exclude ambiguous characters and enforce a minimum random length.
- **Change**: new settings: *Bind Challenge Ports To*, *Renewal Extension*, *Auto-ban Threshold*, *Audit Retention*, Traefik entrypoint/TLS.
- **Change**: background jobs coalesce, run on a 30s cadence, and prune old records.
- **Build**: `requirements.txt` is now version-bounded and complete (`requests` was missing); `docker/` ships a Dockerfile + `constraints.txt` that install it into the CTFd image without breaking CTFd's own pins.
