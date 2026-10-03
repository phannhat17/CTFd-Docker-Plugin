# Troubleshooting

## The plugin does not load

**Symptom.** CTFd starts but there is no Containers menu, and the log shows:

```
AttributeError: module 'CTFd.plugins.containers' has no attribute 'load'
```

or

```
ModuleNotFoundError: No module named 'docker'
```

**Cause.** The first message means the plugin folder is not in the right place, or is empty. The second means the Python dependencies are missing.

**Fix.**

1. Confirm the folder is `CTFd/plugins/containers` and contains `__init__.py`. The folder name must be exactly `containers`, because CTFd derives the module name from it.
2. Install the dependencies. See [installation.md](installation.md), step 2. If you bind mount the plugin, `docker compose up` alone does not install anything; use `--build`, or install into the running container.

## The console shows Docker unreachable

**Symptom.** The sidebar indicator is red, and the Instances tab shows no containers.

**Cause.** The plugin cannot reach the Docker daemon.

**Fix.**

1. Check the socket is mounted:
   ```sh
   docker exec -it <ctfd-container> ls -l /var/run/docker.sock
   ```
2. Check the container can use it:
   ```sh
   docker exec -it <ctfd-container> docker version
   ```
The CTFd image has no `docker` CLI, so use the API instead:
   ```sh
   curl -s -b cookies.txt http://localhost:8000/admin/containers/api/docker/health
   ```
3. Confirm the connection type and socket path on the Settings tab. The default is `unix://var/run/docker.sock`.
4. Check the daemon is running on the host.

## Fetch Instance returns "Docker is not connected"

The same cause as above, hit at the moment a player clicked the button. The Docker client is created at plugin load and reused. Save the settings once to force a reconnect.

## Fetch Instance returns "No available ports in range"

**Cause.** Every port in the configured range is held by a live instance.

**Fix.**

1. Look at **Free ports** on the Instances tab.
2. Check for rows stuck in `running` whose containers no longer exist. Clean them up with **Delete** or **Clean expired**.
3. Widen the range. Remember that a multi port challenge consumes one port per exposed port.
4. Check nothing else on the host is using the range.

## "Failed to provision container: ... image ... not found"

**Cause.** The image is not present on the Docker host, and the pull failed.

**Fix.**

1. Pull it on the host:
   ```sh
   docker pull nginx:latest
   ```
2. Confirm the name matches, including the tag. `nginx` and `nginx:latest` are usually the same, but `ubuntu` and `ubuntu:20.04` are not.
3. Check the host can reach the registry, if the pull is failing for network reasons.

## Container starts but the player cannot reach it

**Symptom.** The panel shows a link, but it does not load.

**Fix.**

1. Confirm **Connection hostname** is reachable from the player's browser, not only from the Docker host. `localhost` only works when the browser is on the same machine.
2. Check the port is open in the firewall. Docker publishes ports by writing its own iptables rules, which bypass UFW:
   ```sh
   curl -v http://<connection-host>:<port>/
   ```
3. Confirm the challenge inside the container listens on the configured internal port. A container that listens on 80 while the challenge says 8080 will produce a link that refuses connections.
4. If **Bind challenge ports to** is set, confirm the IP is correct.

## Containers do not expire on time

**Cause.** Redis keyspace notifications are not active, so expiry relies on the 30 second sweep.

**Fix.**

1. Confirm Redis is configured in CTFd with `REDIS_URL`.
2. Confirm the Redis server was started with notifications enabled:
   ```sh
   docker exec -it <redis-container> redis-cli config get notify-keyspace-events
   ```
The value must contain both `E` and `x`.
3. Check the CTFd log for this line at startup:
   ```
   Redis expiration service ready
   ```
If it instead says the cache backend is not Redis, notifications are off and the sweep is the only mechanism.

## A player sees another challenge's connection details

This was a bug and is fixed. If you still see it, confirm the plugin files were actually reloaded, since a bind mounted plugin needs a CTFd restart to pick up changes to `assets/view.js`:

```sh
docker compose restart ctfd
```

The browser may also have the old script cached. A hard reload clears it.

## Stop or Delete in the console does nothing

**Symptom.** The button does not respond, or a notification reads `HTTP 403`.

**Cause.** A CSRF rejection. CTFd only checks the `CSRF-Token` header when the request declares `Content-Type: application/json`. A body-less POST sent without that content type is treated as a form submission and rejected.

**Fix.** This is fixed in the current version. If you have modified the console, make sure every write request goes through the shared `api()` helper, which always sets the content type.

## The player's flag is rejected as "This flag has expired"

**Cause.** The container expired, which invalidated the flag.

**Fix.** Fetch a new instance, which generates a new flag. This is expected behaviour, not an error.

## Auto-ban did not trigger even though reuse was detected

**Cause.** The threshold is 0, which disables auto-banning.

**Fix.** Set **Auto-ban threshold** to 1 or more on the Settings tab. Detections are always logged regardless of the threshold.

## Import reports "Missing required column(s)"

**Cause.** One of `name`, `category`, or `image` is missing from the header row.

**Fix.** Download the template again and compare the header. Header names are case insensitive, but they must match otherwise.

## Admin pages return 500 after an upgrade

**Cause.** A schema change that `create_all` does not apply, since it only creates missing tables and never alters existing ones.

**Fix.** Back up the database, then compare the model definitions in `models/` with the actual table structure and apply the difference manually, or drop the plugin tables and let them be recreated if the history is disposable.

## Collecting information for a bug report

```sh
# plugin version and settings
curl -s -b cookies.txt http://localhost:8000/admin/containers/api/config

# docker connectivity
curl -s -b cookies.txt http://localhost:8000/admin/containers/api/docker/health

# instance state
docker ps -a --filter label=ctfd.managed=true

# recent plugin log lines
docker compose logs ctfd | grep "CTFd.plugins.containers" | tail -50
```

Include the audit trail entry for the affected instance. It usually identifies which step failed.
