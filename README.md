# CTFd Docker Containers Plugin

A CTFd plugin that gives every team (or every user) their own Docker container for a challenge. A player clicks **Fetch Instance**, a container starts, and the connection details appear on the challenge page. Containers expire on their own, and the plugin keeps an audit trail of everything that happens.

![Containers console](docs/images/admin-console-instances.png)

## Features

- One container per account per challenge, started on demand
- Automatic expiry with exact timing through Redis, plus a 30 second sweep as a backup
- A unique flag per container, encrypted at rest, or a shared static flag if you prefer
- Optional dynamic scoring with linear or logarithmic decay
- Multiple internal ports per challenge, with one link per port
- Subdomain routing through Traefik for web challenges
- Detection of flag sharing, logged and alerted, with optional auto-ban
- Admin console for instances, settings, cheat logs, the audit trail, and CSV or Excel import

## Requirements

- CTFd 3.4 or newer, tested against 3.7.7
- Docker on the CTFd host, or reachable over SSH
- Redis is optional, but recommended for exact expiry timing

## Quick start

1. Put this repository in `CTFd/plugins/containers` and mount the Docker socket into the CTFd container.
2. Install the plugin dependencies. They are not part of the stock CTFd image, and a bind mount does not install them automatically, so build the image with the Dockerfile in `docker/`.
3. Start Redis with `--notify-keyspace-events Ex` for second accurate expiry.
4. Open **Admin, Containers, Console**, then **Settings**, and set **Connection hostname** to an address your players can reach. It must not be the CTFd hostname.
5. Create a challenge of type **container**, then click **Fetch Instance** on it to verify.

Full instructions are in [docs/installation.md](docs/installation.md).

## Documentation

| Document | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Requirements, Docker setup, dependencies, first run |
| [Configuration](docs/configuration.md) | Every setting and what it changes |
| [Creating challenges](docs/challenges.md) | Images, ports, flags, scoring, limits |
| [Player guide](docs/player-guide.md) | What a player sees and can do |
| [Admin console](docs/admin-console.md) | The console, tab by tab |
| [Anti-cheat](docs/anti-cheat.md) | Flag reuse detection, the two outcomes, auto-ban |
| [Import](docs/import.md) | CSV and Excel bulk import |
| [Operations](docs/operations.md) | Background jobs, expiry, retention, recovery |
| [Security](docs/security.md) | Isolation model and its limits |
| [Troubleshooting](docs/troubleshooting.md) | Common errors and fixes |
| [Changelog](docs/changelog.md) | What changed and why |

## Security warning

Browsers send cookies to every port on a hostname. If challenge containers are published on the same hostname as CTFd, a challenge with a remote code execution bug can steal player session cookies. Use a separate hostname or IP for challenges. See [docs/security.md](docs/security.md).

## License

See [LICENSE](LICENSE).
