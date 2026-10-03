---
title: Security
description: "Cookie exposure, container isolation, and what each control really blocks."
---

# Security

This document describes what the plugin protects against, what it does not, and which settings matter most.

## The main risk: cookies are shared across ports

Browsers send cookies to every port on a hostname. They do not scope cookies by port.

If the CTFd platform is at `ctf.example.com` and challenge containers are published on `ctf.example.com:30000`, then a challenge with a remote code execution vulnerability runs on the same origin as CTFd. The container can read the `session` cookie of any player who visits it, which is a full account takeover.

This is not specific to this plugin. It applies to every CTFd container plugin that publishes ports on the CTFd hostname.

### What to do

Set **Connection hostname** to something that is not the CTFd hostname:

| Configuration | Safe |
| --- | --- |
| CTFd at `ctf.example.com`, challenges at `challenges.example.com` | yes |
| CTFd at `ctf.example.com`, challenges at `203.0.113.10` | yes |
| CTFd at `ctf.example.com`, challenges at `challenges-ctf.org` | yes |
| CTFd at `ctf.example.com`, challenges at `ctf.example.com:30000` | **no** |

The cookie has to be scoped to the CTFd hostname for this to work, which is CTFd's default behaviour.

## Container isolation

Each container gets the following.

| Control | Setting | Blocks |
| --- | --- | --- |
| Capabilities dropped | `cap_drop: ALL` | Most privileged operations |
| Selected capabilities added back | `CHOWN`, `SETUID`, `SETGID` | Needed by many images at startup |
| Privilege escalation | `no-new-privileges` | A setuid binary raising privileges |
| Process limit | `pids_limit` | Fork bombs |
| Memory limit | `mem_limit` | Memory exhaustion |
| CPU limit | `cpu_quota` | CPU exhaustion |
| Network isolation | `enable_icc=false` | Direct container to container traffic |

Containers still run as root inside their own namespace. That is deliberate: many CTF challenges ask the player to obtain root inside the container, which is the objective of the challenge. Removing root would break those challenges.

### What network isolation does and does not cover

The isolated network blocks direct container to container connections. Measured behaviour:

| Path | Result |
| --- | --- |
| Container A to container B by IP | blocked |
| Container A to container B by container name | blocked |
| Container A to an internal port on B | blocked |
| ARP spoofing or promiscuous sniffing | blocked, no `CAP_NET_RAW` |
| Container A to a published port of B through the gateway | **reachable** |
| Docker DNS listing other containers | **reachable** |

The last two rows are worth understanding.

Docker's `enable_icc=false` blocks layer 2 traffic between containers on the same bridge. It does not block traffic to the bridge gateway, which is the host itself. A published port is reachable through that gateway, so a player who has code execution inside their own container can reach another team's published port if they know its number. Docker's embedded DNS also resolves container names across the whole network, so the container names are discoverable.

The practical impact depends on the challenge:

- A static service, such as an nginx that only serves a fixed file, has nothing to steal. Reading another team's identical container changes nothing.
- A challenge with private mutable state, such as a database, a file upload endpoint, or an application with per team sessions, is affected. One team can read or modify another team's instance.

### Reducing the exposure

Three options, in increasing order of effort.

**1. Bind ports to one interface.** Set **Bind challenge ports to** to the public IP of the challenge host. This does not stop a container from reaching another container through the gateway, but it removes the port from any other interface.

**2. Use per challenge networks.** Give each challenge its own Docker network, so the gateway of that network only forwards to containers of the same challenge and the DNS zone only contains those containers. A team could still reach another team solving the same challenge, but nothing else.

The limit to plan for is Docker's address pool. By default the daemon can only allocate 31 networks (15 subnets of `/16` in `172.17.0.0/16` through `172.31.0.0/16`, plus 16 subnets of `/20` in `192.168.0.0/16`), and an empty network still occupies one of them. The error when it runs out is:

```
Error response from daemon: all predefined address pools have been fully subnetted
```

Raise the ceiling in `/etc/docker/daemon.json` on the host:

```json
{
  "default-address-pools": [
    { "base": "10.0.0.0/8", "size": 24 }
  ]
}
```

Then restart Docker. That changes the ceiling from 31 networks to 65536.

**3. Use a stronger runtime.** gVisor or Kata Containers emulate the syscall surface, so a kernel exploit inside the challenge does not reach the host kernel. Rootless Docker or `userns-remap` achieves a similar effect for privilege escalation, because root inside the container maps to an unprivileged user on the host.

### What about root inside the container

A player with root inside their own container can:

- Read their own flag. That is the intended path.
- Read the container's environment, which includes `FLAG`.
- Attack the kernel, which the container runtime and host hardening should stop.
- Reach published ports through the gateway, as described above.

They cannot read another account's flag from the database, because the database is not reachable from the challenge network.

## Flag handling

| Property | Implementation |
| --- | --- |
| At rest | Fernet encryption, key generated on first use |
| Lookup | Keyed HMAC-SHA256 over the flag |
| Comparison | Constant time |
| Scope | Per challenge, checked on every submission |
| Lifetime | Invalidated when the container expires unsolved |

The Fernet key is stored in `container_config` in the same database as the encrypted flags. A full database dump therefore contains both. The encryption raises the effort needed to use a dump, it does not make the flags cryptographically out of reach.

The HMAC key is derived from the Fernet key, so no separate secret has to be managed. The consequence is the same: a database dump is enough to verify a guess at a flag.

If that matters for your event, protect the database with normal means: credentials that are not shared, network isolation between the database and the internet, and access control on the host.

## Admin surface

| Concern | Handling |
| --- | --- |
| Authentication | CTFd admin session on every console route |
| CSRF | CTFd's `CSRF-Token` header check |
| Setting writes | Allow-list of keys, each with a validator |
| Secret exposure | The encryption key is never returned by the config API |
| SSH material | Values are validated before they are written to `~/.ssh` |
| Destructive actions | Confirmation dialog in the UI |

The SSH writer deserves a note. It composes an `ssh_config` file and a `known_hosts` entry from admin input. Hostnames are restricted to letters, digits, dots, and dashes, the user is restricted to a safe set, the port must be an integer, and the known hosts entry must be a single line. Without those checks a newline could inject additional SSH options.

## Recommendations for an event

1. Use a separate hostname or IP for challenges, always.
2. Keep CTFd itself off the isolated network, so containers cannot reach it.
3. Set a memory limit that matches the challenge images. The default of 512 MB is a reasonable starting point for small images.
4. If a challenge does not need internet access, place it on a network with `internal: true` rather than the default bridge.
5. Add a `DOCKER-USER` rule if you need to filter the published port range, because Docker's published ports bypass host firewall rules such as UFW:

   ```sh
   iptables -I DOCKER-USER -p tcp --dport 30000:31000 -j DROP
   ```

6. Keep auto-ban off, or set the threshold to 3 or more.
7. Watch the audit trail during the event. It records every stop, expiry, and reuse detection with a timestamp.

## Reporting a problem

Security issues in the plugin should be reported privately to the maintainer rather than in a public issue.
