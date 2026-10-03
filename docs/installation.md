---
title: Installation
description: "Requirements, Docker setup, dependencies and the first run."
---

# Installation

## Requirements

- CTFd 3.4 or newer. Tested against CTFd 3.7.7.
- Docker on the machine that runs CTFd, or on a machine it can reach over SSH.
- Redis (optional but recommended). Without Redis, containers still expire, but only on a 30 second sweep instead of exactly on time.
- Python packages that are listed in the plugin's `requirements.txt`. These are not part of the stock CTFd image.

## Step 1: place the plugin

Clone or copy the repository into the CTFd plugins directory and name the folder `containers`. The folder name matters because CTFd derives the plugin module name from it.

```
CTFd/
  plugins/
    containers/        <- this repository
      __init__.py
      models/
      routes/
      services/
      templates/
      assets/
      docs/
```

## Step 2: install the Python dependencies

The plugin imports `docker`, `apscheduler`, `openpyxl`, and `paramiko` when it loads. The stock CTFd image does not include them.

CTFd does have a mechanism that installs a plugin's `requirements.txt` automatically, but it only runs while CTFd builds its **own** image, and only for plugins that are part of the build context. If you bind mount the plugin as a volume, which is the usual way while developing, `docker compose up` installs nothing and the plugin fails to load with:

```
ModuleNotFoundError: No module named 'docker'
```

Pick one of these two approaches.

### Option A: bake the dependencies into the image (recommended)

Keep the plugin and a small Dockerfile together. The deployment in this repository uses the repository root as the build context so the plugin's own `requirements.txt` is the single source of truth:

```dockerfile
FROM ctfd/ctfd:3.7.7

COPY CTFd-Docker-Plugin/requirements.txt /opt/ctfd-containers/requirements.txt
COPY docker/constraints.txt /opt/ctfd-containers/constraints.txt
RUN /opt/venv/bin/pip install --no-cache-dir \
        -c /opt/ctfd-containers/constraints.txt \
        -r /opt/ctfd-containers/requirements.txt
```

Always start the stack with `docker compose up -d --build`.

The `constraints.txt` file pins the transitive `cffi` dependency. Without it, `paramiko` pulls `cryptography`, which pulls `cffi` 2.x, and CTFd pins `pybluemonday==0.0.14`, which requires `cffi~=1.1`. The build then reports:

```
ERROR: pip's dependency resolver ... pybluemonday 0.0.14 requires cffi~=1.1,
but you have cffi 2.1.1 which is incompatible.
```

### Option B: install into a running container

```sh
docker exec -it <ctfd-container> sh -c \
    "printf 'cffi<2\n' > /tmp/ctfd-containers-constraints.txt && \
     /opt/venv/bin/pip install \
        -c /tmp/ctfd-containers-constraints.txt \
        -r /opt/CTFd/CTFd/plugins/containers/requirements.txt"
```

`/opt/venv` is owned by root, so this only works when the container runs as root. With CTFd's default non-root user, add `-u root` to `docker exec`.

The install is lost when the container is recreated, so treat this as a development convenience, not a deployment method.

## Step 3: mount the Docker socket

The plugin talks to the Docker daemon through the mounted socket:

```yaml
services:
  ctfd:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

The CTFd container normally runs as root, which is what makes the socket usable.

## Step 4: enable Redis keyspace notifications

```yaml
services:
  cache:
    image: redis:4
    command: redis-server --notify-keyspace-events Ex --appendonly yes
```

The plugin sets a Redis key with a TTL for each instance. When the key expires, Redis publishes an event, the plugin receives it, and the container is stopped at that moment. Without this, expiry falls back to the 30 second sweep.

The plugin checks the server setting on startup and only tries to change it when notifications are not already enabled, so managed Redis services that disable `CONFIG SET` are handled gracefully.

## Step 5: a complete compose example

```yaml
services:
  ctfd:
    build:
      context: .
      dockerfile: docker/Dockerfile
    user: root
    ports:
      - "8000:8000"
    environment:
      - UPLOAD_FOLDER=/var/uploads
      - DATABASE_URL=mysql+pymysql://ctfd:ctfd@db/ctfd
      - REDIS_URL=redis://cache:6379
      - WORKERS=1
      - LOG_FOLDER=/var/log/CTFd
    volumes:
      - .data/CTFd/logs:/var/log/CTFd
      - .data/CTFd/uploads:/var/uploads
      - /var/run/docker.sock:/var/run/docker.sock
      - ./CTFd-Docker-Plugin:/opt/CTFd/CTFd/plugins/containers
    depends_on:
      - db
      - cache

  db:
    image: mariadb:10.11
    environment:
      - MARIADB_ROOT_PASSWORD=ctfd
      - MARIADB_USER=ctfd
      - MARIADB_PASSWORD=ctfd
      - MARIADB_DATABASE=ctfd

  cache:
    image: redis:4
    command: redis-server --notify-keyspace-events Ex --appendonly yes
```

## Step 6: verify the installation

1. Open CTFd. The plugin creates its database tables on first load.
2. Go to **Admin, Containers, Console**. The sidebar shows a Docker status indicator. It should read **Docker connected**.
3. If it reads **Docker unreachable**, open the **Settings** tab and check the connection type and socket path.
4. Create a test challenge of type **container**, then click **Fetch Instance** on its challenge page.

## What the plugin creates on first load

| Table | Purpose |
| --- | --- |
| `container_challenge` | Container specific fields for a challenge |
| `container_instances` | One row per spawned container |
| `container_flags` | Flag records for reuse detection |
| `container_flag_attempts` | Every flag submission (correct, wrong, or reuse) |
| `container_audit_logs` | Lifecycle events with severity |
| `container_config` | Plugin settings, key and value pairs |

Existing challenges and user data are not modified.

## Upgrading

Replace the plugin folder and restart CTFd. Tables are created with `create_all`, which does not alter existing tables, so schema changes in a new version may need a manual migration. Back up the database before upgrading a live event.

## Uninstalling

Remove the plugin folder, restart CTFd, and stop any containers the plugin started. Containers carry the label `ctfd.managed=true`, so they are easy to find:

```sh
docker ps -a --filter label=ctfd.managed=true
docker rm -f $(docker ps -aq --filter label=ctfd.managed=true)
```

The plugin's tables can be dropped afterwards if you do not need the audit history.
