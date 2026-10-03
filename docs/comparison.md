---
title: Comparison
description: "How this plugin compares with other CTFd container plugins and with rCTF, kCTF and redpwn/jail."
---

# Compared with other projects

Several projects solve the same problem. This page puts them side by side so you can pick the right one, or decide that this one is not right for you.

Two notes on how to read it. The facts come from each project's own documentation and from its GitHub metadata on 2026-10-03, not from running them side by side, so treat the other projects' rows as "what their docs claim". And a comparison written by the author of one of the entries is not a neutral source, so the section on where this plugin loses is deliberately specific.

## The landscape

They fall into two groups. Either a plugin that runs inside CTFd and talks to Docker, or a separate orchestration service that is bigger than CTFd.

| Project | Kind | Architecture it needs | Stars | Last push | License |
| --- | --- | --- | --- | --- | --- |
| **This plugin** | CTFd plugin | Docker socket, optional Redis | 31 | active | MIT |
| [andyjsmith/CTFd-Docker-Plugin](https://github.com/andyjsmith/CTFd-Docker-Plugin) | CTFd plugin | Docker socket | 28 | 2022-06-27 | MIT |
| [TheFlash2k/containers](https://github.com/TheFlash2k/containers) | CTFd plugin | Docker socket | 21 | 2024-10-18 | MIT |
| [frankli0324/ctfd-whale](https://github.com/frankli0324/ctfd-whale) | CTFd plugin | Docker Swarm plus frp, Redis required | 181 | 2026-04-05 | MIT |
| [BIT-NSC/CTFd-owl](https://github.com/BIT-NSC/CTFd-owl) | CTFd plugin | docker-compose, CTFd 3.4.0 | 23 | 2022-03-26 | Apache-2.0 |
| [rCTF Instancer](https://rctf.osec.io/integrations/instancer/) | Separate platform | Docker service or Kubernetes | 130 | 2026-09-22 | Apache-2.0 |
| [kCTF](https://google.github.io/kctf/introduction.html) | Separate platform | Kubernetes plus nsjail | 795 | 2026-03-25 | Apache-2.0 |
| [redpwn/jail](https://github.com/redpwn/jail) | Not the same thing | Docker image, used with any platform | 261 | 2024-07-17 | BSD-3-Clause |

This plugin descends from andyjsmith's, which is the oldest of the CTFd plugins and has not been touched since 2022. TheFlash2k's is a second descendant of the same base and added user mode and core-beta theme support.

## What each one gives you

| Capability | This plugin | andyjsmith | Flash2k | whale | owl | rCTF | kCTF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| One instance per team | yes | yes | yes | yes | yes | yes | yes |
| Per-instance flags | yes | partial | partial | yes | yes | yes | yes |
| Flag sharing detection | yes | no | no | not documented | not documented | no | no |
| Dynamic scoring | yes | yes | yes | no | no | via scoring providers | no |
| Multiple internal ports | yes | no | no | no | yes | yes | no |
| Subdomain routing | yes, Traefik | no | no | yes, frp | yes, Traefik | yes, Traefik | yes, Kubernetes ingress |
| Multi-container challenge | no | no | no | no | yes, compose | yes, compose-like | no |
| Admin console | yes | basic | basic | yes | yes | yes | limited |
| Audit trail | yes | no | no | no | no | yes | logs |
| Bulk CSV or Excel import | yes | no | no | no | no | yes, YAML | manifests |
| Auto-expiry | yes, Redis plus sweep | polling | polling | yes | yes | yes | yes |
| Setup effort | low | low | low | high | medium | high | high |
| Runs without extra services | yes | yes | yes | no, needs Swarm and frp | no, needs compose | no | no |

"Not documented" means the project's README and docs do not describe it. It may exist in the code.

## Where this plugin is the better choice

**Setup is the smallest of the group.** The others need something beyond a Docker socket: whale needs a Swarm cluster and an frp relay, owl needs docker-compose, rCTF needs a separate FastAPI service or a Kubernetes operator, kCTF needs a Kubernetes cluster. For a small CTF on one machine, this plugin is a volume mount and a settings page.

**Flag sharing detection is close to unique.** None of the other CTFd plugins document detecting that a player submitted another team's flag, and neither rCTF nor kCTF advertise it. If you care about flag sharing, this is the only one that gives you a cheat log out of the box.

**Audit trail.** Every lifecycle event is written with a severity, an actor and a details payload, and the console has a viewer for it. whale and owl do not document anything similar.

**Bulk import.** A CSV or Excel file creates a whole category at once, which matters on the day you are loading 40 challenges. rCTF uses YAML elsewhere, whale and owl have no import.

**Dynamic scoring without extra work.** Linear and logarithmic decay are built in. The other CTFd container plugins either do not support it or require you to wire CTFd's own dynamic type separately.

## Where this plugin is worse

These are real. If any of them is a hard requirement for your event, use another project.

**Isolation is weaker than kCTF and rCTF.** This plugin drops all capabilities, adds three back, sets `no-new-privileges`, and puts containers on a bridge with inter-container communication disabled. There is no seccomp profile beyond Docker's default, no AppArmor profile, and the container runs as root inside its own namespace. That last part is deliberate, because many challenges ask the player to become root, but it does mean a kernel exploit is the boundary. kCTF runs challenges under nsjail on Kubernetes, and rCTF's own documentation opens with a warning to treat challenge images as hostile.

**Inter-container traffic is not fully blocked.** I measured this on a live deployment. With `enable_icc=false`, another container cannot reach yours by IP, by name, or on an internal port, and ARP spoofing is blocked because there is no `CAP_NET_RAW`. But a published port is reachable through the bridge gateway, and Docker's embedded DNS lists every container name on the network. A team with code execution in their own container can reach another team's published port if they find the number. The practical impact depends on the challenge: a static service has nothing to steal, a challenge with private mutable state does. See [security.md](security.md) for the measurements and for the mitigations.

**Provisioning blocks the request.** `Fetch Instance` does not return until the container is running. With local images that is under a second, so it rarely matters, but a slow image pull keeps the HTTP request open. rCTF returns `starting` immediately and the client polls.

**One Docker host.** There is no scheduler across several machines and no per-host port partitioning. whale uses Swarm, rCTF runs on Docker or Kubernetes, and kCTF is Kubernetes native. If you need several challenge hosts behind one CTFd, this plugin is not the tool.

**Resource limits are global.** Memory, CPU and the process limit apply to every container. rCTF and kCTF configure resources per challenge. The columns for per-challenge limits exist in the model but the code ignores them.

**No multi-container challenges.** CTFd-owl was built for docker-compose challenges and this plugin cannot do them. If a challenge needs a web app plus a database, owl or rCTF is the right answer.

**No admin bot.** rCTF ships an admin bot for web challenges, including a queue and logs. This plugin has nothing for that.

**Testing is newer.** rCTF and kCTF are organised projects with their own test suites and continuous integration. The test suites in this repository were added during the review that produced version 2.1.0, so they are young.

## Choose by situation

| Your situation | Reasonable choice |
| --- | --- |
| One machine, a weekend CTF, want it running today | This plugin, or Flash2k's if you do not need anti-cheat |
| Same, and you care about flag sharing | This plugin |
| Challenges that need several containers | CTFd-owl, or rCTF |
| Hundreds of teams, several challenge hosts | rCTF, or kCTF |
| Google scale, dedicated infrastructure team | kCTF |
| You want a per-connection jail for pwn challenges only | redpwn/jail, with whichever platform you already use |
| You inherited an andyjsmith or Flash2k deployment | Migrate to this plugin, or stay if it works for you |

## redpwn/jail is a different tool

It is worth separating, because it solves an adjacent problem rather than competing. redpwn/jail is an nsjail based Docker image that starts one jail per incoming TCP connection, with proof of work and per-connection CPU, memory, PID and disk limits. It is not a CTFd plugin and does not manage per-team instances. You run it as the challenge image itself, on any platform, including this one.

That combination is worth knowing about: this plugin can spawn redpwn/jail as the challenge container, which gives you per-team instance lifecycle from CTFd plus per-connection jailing inside. The two are complementary.

## Summary

The honest shape of it is this. This plugin is the easiest of the group to stand up, and the only CTFd plugin here with flag sharing detection and an audit trail. It is not the strongest on isolation, it does not scale past one host, and it cannot run multi-container challenges. If your event is one machine and tens to a few hundred teams, it is a good fit. If it is larger, or the challenges are hostile by design, rCTF or kCTF is the better foundation and the extra setup is buying something real.
