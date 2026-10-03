# Containers plugin documentation

A CTFd plugin that gives every team (or every user, depending on the CTF mode) its own Docker container for a challenge. A player clicks one button, a container starts, and the connection details appear on the challenge page. Containers expire on their own, and the plugin keeps an audit trail of everything that happens.

## What this plugin does

- Spawns one container per account for a challenge, on demand.
- Generates a unique flag per container (or uses a shared static flag).
- Stops the container automatically when the flag is solved or the timer runs out.
- Detects when a player submits another account's flag.
- Gives admins a console for instances, settings, cheat logs, the audit trail, and bulk CSV import.
- Isolates challenge containers from each other and from the CTFd host.

## Documentation index

| Document | What it covers |
| --- | --- |
| [installation.md](installation.md) | Requirements, Docker setup, dependencies, first run |
| [configuration.md](configuration.md) | Every admin setting and what it changes |
| [challenges.md](challenges.md) | Creating a container challenge, images, ports, flags, scoring |
| [player-guide.md](player-guide.md) | What a player sees and can do |
| [admin-console.md](admin-console.md) | The new console, tab by tab |
| [anti-cheat.md](anti-cheat.md) | Flag reuse detection, alerts, optional auto-ban |
| [import.md](import.md) | CSV and Excel bulk import |
| [operations.md](operations.md) | Cleanup jobs, expiring instances, database tables |
| [security.md](security.md) | Isolation model, what it does and does not protect against |
| [troubleshooting.md](troubleshooting.md) | Common errors and how to fix them |

## Quick start

1. Put the plugin in `CTFd/plugins/containers` and mount the Docker socket into the CTFd container. See [installation.md](installation.md).
2. Open **Admin, Containers, Console**, then the **Settings** tab.
3. Set **Connection hostname** to an address your players can reach, for example `challenges.example.com` or the public IP of the challenge host.
4. Create a challenge of type **container** and pick an image that already exists on the Docker host.
5. Click **Fetch Instance** on the challenge page to verify a container starts.

The container timer defaults to 60 minutes, and the plugin kills the container when it expires.
