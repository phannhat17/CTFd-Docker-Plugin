# Configuration

All settings live in **Admin, Containers, Console**, on the **Settings** tab. They are stored in the `container_config` table and take effect immediately. No restart is needed, except when you change the Docker connection and the new endpoint is unreachable.

![Settings tab](images/admin-console-settings.png)

## Docker connection

| Setting | Default | Notes |
| --- | --- | --- |
| Connection type | Local socket | `local` uses the mounted socket. `ssh` uses a remote daemon. |
| Docker socket / base URL | `unix://var/run/docker.sock` | For a TCP daemon use `tcp://host:2376`. |
| SSH host | empty | Only for the `ssh` connection type. |
| SSH user | `root` | Must be able to reach the Docker socket on the remote host. |
| SSH port | `22` | |
| Known hosts entry | empty | A single line, for example `host ssh-ed25519 AAAA...`. |

When you save an SSH connection, the plugin writes the key, a `known_hosts` entry, and an `ssh_config` block under `~/.ssh` inside the CTFd container, then reconnects. All of these values are validated before they are written, so a newline cannot be used to inject extra SSH options.

The dependency here is `docker-py`, which speaks SSH itself. A plain SSH daemon on the challenge host is enough, and it avoids exposing the Docker API port.

## Instances

| Setting | Default | Notes |
| --- | --- | --- |
| Connection hostname shown to players | `localhost` | Must be reachable from the player's browser. |
| Bind challenge ports to | empty (all interfaces) | Set a specific IP to publish on one interface only. |
| Default timeout | 60 | Minutes before the container is stopped. |
| Max renewals | 3 | How many times a player may extend their instance. |
| Renewal extension | 5 | Minutes added per extension. |
| Max concurrent containers per account | 3 | Applies per team in team mode, per user in user mode. |
| Memory limit | `512m` | Docker memory limit for every challenge container. |
| CPU limit | `0.5` | In cores. `1.5` means one and a half cores. |

**Connection hostname is the most important setting.** Browsers send cookies to every port on a hostname, so if challenge containers share a hostname with CTFd, a challenge with a remote code execution bug can read the CTFd session cookie. Use a separate hostname, a separate domain, or a separate IP. The security document covers this in more detail.

## Ports and networks

| Setting | Default | Notes |
| --- | --- | --- |
| Port range start | 30000 | |
| Port range end | 31000 | |
| Isolated network | `ctfd-isolated` | Network used for host port challenges. |
| Subdomain network | `ctfd-challenges` | Network used when Traefik routes the challenge. |

The plugin creates the isolated network on demand and sets `com.docker.network.bridge.enable_icc=false` on it, which stops containers from reaching each other directly.

Size the port range for the number of simultaneous containers you expect. The console shows the number of free ports on the Instances tab. If the range runs out, `Fetch Instance` returns an error instead of starting a container.

## Subdomain routing (Traefik)

| Setting | Default | Notes |
| --- | --- | --- |
| Enable subdomain routing | off | Only applies to challenges whose connection type is `http`, `https`, or `web`. |
| Base domain | empty | For example `challenges.example.com`. A wildcard DNS record is required. |
| Traefik entrypoint | `web` | The entrypoint Traefik listens on. |
| Use TLS | off | Adds the `tls=true` router label and shows `https://` links. |

When subdomain routing is enabled for a challenge, no host port is published at all. Traefik reaches the container over the Docker network instead, so the port range is not consumed.

Each instance gets a random single level subdomain such as `c-9f2a1b3c4d5e6f70.challenges.example.com`. A single level name is used because free wildcard certificates, Cloudflare in particular, only cover one level.

For challenges with multiple internal ports, the primary port gets the base subdomain and each additional port gets a `-port` suffix:

```
80   -> c-9f2a1b3c4d5e6f70.challenges.example.com
8080 -> c-9f2a1b3c4d5e6f70-8080.challenges.example.com
```

Requirements:

- Traefik running with the Docker provider enabled and pointed at the same network you configure here.
- A wildcard DNS record for the base domain.
- Challenge containers attached to that network, which the plugin does.

See [SUBDOMAIN_INFO.md](../SUBDOMAIN_INFO.md) in the repository root for a deployment walkthrough.

## Anti-cheat and retention

| Setting | Default | Notes |
| --- | --- | --- |
| Auto-ban threshold | 0 | `0` means never ban automatically. |
| Log every flag attempt | on | Turn off on very large events to reduce database writes. |
| Audit retention | 7 | Days that stopped, solved, and errored instance records are kept. |

The threshold counts detections on the same challenge for the same account. When the count reaches the threshold, both the submitting account and the flag owner are banned. Because submitting somebody else's flag is trivial to do on purpose, the default is 0 and banning is an explicit decision. The anti-cheat document explains the reasoning.

## Notifications

| Setting | Default | Notes |
| --- | --- | --- |
| Discord webhook URL | empty | Optional. Used for flag reuse alerts and provisioning errors. |

Three buttons send a test message: **Test connection**, **Demo cheat alert**, and **Demo error alert**. They use the URL currently typed in the field, so you can validate it before saving.

Discord is the only notification target. The payload is a standard webhook embed, so a compatible endpoint that accepts the same JSON also works.

## Saving settings

The save button validates every field before it writes anything:

- Numbers are range checked. A port range where start is greater than end is rejected.
- Hostnames are checked against a safe character set.
- Booleans are normalized to `true` or `false`.
- Keys that are not part of the documented list are ignored and reported back.

If some values were rejected, the response lists them and the rest are saved. The console shows the notes as a notification.

## Configuration reference

| Key | Type | Default |
| --- | --- | --- |
| `docker_type` | `local` or `ssh` | `local` |
| `docker_socket` | string | `unix://var/run/docker.sock` |
| `connection_host` | hostname | `localhost` |
| `port_bind_ip` | hostname or empty | empty |
| `port_range_start` | int | `30000` |
| `port_range_end` | int | `31000` |
| `default_timeout` | int, minutes | `60` |
| `max_renewals` | int | `3` |
| `renew_extension_minutes` | int, minutes | `5` |
| `max_memory` | string | `512m` |
| `max_cpu` | float | `0.5` |
| `container_max_concurrent_count` | int | `3` |
| `isolated_network` | string | `ctfd-isolated` |
| `subdomain_enabled` | bool | `false` |
| `subdomain_base_domain` | hostname | empty |
| `subdomain_network` | string | `ctfd-challenges` |
| `subdomain_entrypoint` | string | `web` |
| `subdomain_tls` | bool | `false` |
| `anticheat_autoban_threshold` | int | `0` |
| `anticheat_log_all_attempts` | bool | `true` |
| `audit_retention_days` | int | `7` |
| `background_jobs_enabled` | bool | `true` |
| `container_discord_webhook_url` | string | empty |
