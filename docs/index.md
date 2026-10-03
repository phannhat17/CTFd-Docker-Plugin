---
layout: home

hero:
  name: CTFd Containers
  text: One Docker container per team
  tagline: A CTFd plugin that starts an isolated container for every team on demand, issues a unique flag, expires it automatically, and keeps a full audit trail.
  actions:
    - theme: brand
      text: Get started
      link: /installation
    - theme: alt
      text: Admin console
      link: /admin-console
    - theme: alt
      text: View on GitHub
      link: https://github.com/phannhat17/CTFd-Docker-Plugin

features:
  - title: On-demand containers
    details: A player clicks Fetch Instance and gets a container of their own. One instance per account per challenge, with configurable memory, CPU and process limits.
  - title: Per-instance flags
    details: Every container gets a unique flag, encrypted at rest and hashed with a keyed HMAC. A flag issued for one challenge never validates on another.
  - title: Precise expiry
    details: Redis keyspace notifications stop the container at the exact expiry second. A 30 second sweep covers deployments without Redis, so nothing is left running.
  - title: Flag sharing detection
    details: Submitting another team's flag is recorded, alerted and shown in the cheat log. Auto-banning is opt-in, because the innocent owner can be targeted.
  - title: Subdomain routing
    details: Web challenges can be served through Traefik on a random subdomain instead of a host port, so the port range is not consumed.
  - title: Admin console
    details: A standalone console for instances, settings, cheat logs, the audit trail and bulk CSV or Excel import.
---

## What this plugin does

A CTFd plugin that gives every team (or every user, depending on the CTF mode) its own Docker container for a challenge. Containers expire on their own, and the plugin keeps an audit trail of everything that happens.

![Containers console](images/admin-console-instances.png)

## Start here

| Document | What it covers |
| --- | --- |
| [Installation](installation.md) | Requirements, Docker setup, dependencies, first run |
| [Configuration](configuration.md) | Every setting and what it changes |
| [Creating challenges](challenges.md) | Images, ports, flags, scoring, limits |
| [Player guide](player-guide.md) | What a player sees and can do |
| [Admin console](admin-console.md) | The console, tab by tab |
| [Anti-cheat](anti-cheat.md) | Flag reuse detection, the two outcomes, auto-ban |
| [Subdomain routing](subdomain-routing.md) | Serving web challenges through Traefik |
| [Import](import.md) | CSV and Excel bulk import |
| [Operations](operations.md) | Background jobs, expiry, retention, recovery |
| [Security](security.md) | Isolation model and its limits |
| [Troubleshooting](troubleshooting.md) | Common errors and fixes |
| [Compared with other projects](comparison.md) | whale, CTFd-owl, rCTF, kCTF, redpwn/jail |
| [Changelog](changelog.md) | What changed and why |

## Security warning

Browsers send cookies to every port on a hostname. If challenge containers are published on the same hostname as CTFd, a challenge with a remote code execution bug can steal player session cookies. Use a separate hostname or IP for challenges. See [Security](security.md) for the full picture.
