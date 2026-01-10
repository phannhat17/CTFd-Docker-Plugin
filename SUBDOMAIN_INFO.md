# Subdomain Routing Guide for CTFd Containers Plugin

## 1. Architecture Overview

Traditionally, container challenges are accessed via `HOST:PORT` (e.g., `ctf.example.com:30001`). Subdomain routing allows access via unique URLs (e.g., `https://c-a1b2c3d4.ctf.example.com`) without exposing ports on the host server.

**Traffic Flow:**
1.  **User** visits `https://c-a1b2c3d4.example.com`
2.  **Cloudflare DNS** resolves to Cloudflare Tunnel.
3.  **Cloudflare Tunnel** forwards traffic to the `traefik` container.
4.  **Traefik** reads the Host header (`c-a1b2c3d4.example.com`), looks up the active Docker container with the matching UUID label, and routes the request to that container's internal port.

## 2. Components

*   **Cloudflare Tunnel (`cloudflared`)**: Exposes the local Traefik service to the internet without opening ports on your router/firewall. Handles SSL termination.
*   **Traefik**: A modern reverse proxy that listens to Docker events. It automatically reconfigures routing rules when a challenge container starts or stops.
*   **CTFd Plugin**: Generates random subdomains and assigns specific Traefik labels to Docker containers when they are created.

## 3. Configuration Steps

### Step 1: Cloudflare Setup (Critical)

1.  **DNS Record**:
    *   Go to Cloudflare Dashboard -> DNS.
    *   Create a **CNAME** record:
        *   **Name**: `*` (Wildcard) - *Required for Cloudflare Free SSL to work*
        *   **Target**: Your Tunnel URL (e.g., `uuid.cfargotunnel.com`) or your server domain if managing tunnel differently.
        *   **Proxy Status**: On (Orange Cloud).
    
    ![Cloudflare DNS Record](./image-readme/dns.png)

2.  **Tunnel Configuration** (Zero Trust Dashboard):
    *   Add a Public Hostname route:
        *   **Public Hostname**: `*.example.com` (Wildcard)
        *   **Service**: `http://traefik:80`
    *   *Note: This tells Cloudflare to send ANY subdomain request for your domain to the Traefik container.*

    ![Cloudflare Tunnel Configuration](./image-readme/zerotrust.png)

### Step 2: Docker Compose

Ensure `traefik` and `cloudflared` services are running. Example docker compose file [here](./docker-compose.recommended.yml) 
*   **Traefik Version**: Use `v2.11` (stable).
*   **Docker API**: Set `DOCKER_API_VERSION=1.45` environment variable for Traefik to work with modern Docker Engines (v25+).
*   **Network**: All services (`ctfd`, `traefik`, challenge containers) must share a Docker network (e.g., `ctfd-network`).

### Step 3: Plugin Settings (CTFd Admin)

Go to **Admin Panel -> Containers -> Settings**:

1.  **Enable Subdomain Routing**: Checked.
2.  **Base Domain**: Enter your root domain (e.g., `example.com`).
    *   *Do not include `challenge.` prefix if using Cloudflare Free plan (SSL limitations).*
3.  **Docker Network Name**: `ctfd-network` (Must match the network name in `docker-compose.yml`).

![CTFd Plugin Settings](./image-readme/config-sub.png)

## 4. How It Works Internally

When a user starts a web challenge:
1.  Plugin generates a UUID (e.g., `ac3fdbd9`).
2.  Plugin formats subdomain: `c-ac3fdbd9`.
3.  Plugin creates a Docker container with labels:
    ```yaml
    traefik.enable: "true"
    traefik.http.routers.r1.rule: "Host(`c-ac3fdbd9.example.com`)"
    ```
4.  Traefik detects the new container and creates a route.
5.  Plugin returns the URL `https://c-ac3fdbd9.example.com` to the user.

![CTFd Plugin Settings](./image-readme/sub-1.png)
![CTFd Plugin Settings](./image-readme/sub-2.png)

## 5. Troubleshooting

### 404 Page Not Found (from Cloudflare)
*   **Cause**: DNS record missing.
*   **Fix**: Create `*` CNAME record in Cloudflare DNS.

### 404 Page Not Found (from Traefik)
*   **Cause**: Traefik is running but cannot see the container or the route.
*   **Fix**: 
    *   Check if Traefik sees Docker: `docker logs ctfd-traefik-1`. Look for API version errors.
    *   Check container labels: `docker inspect <container_id>`.

### SSL Handshake Failure / Privacy Error
*   **Cause**: Using multi-level subdomain (e.g., `abc.challenge.domain.com`) on Cloudflare Free Plan.
*   **Fix**: Switch to single-level format (`c-abc.domain.com`) by updating Plugin Settings "Base Domain" to root domain.

### Docker API Error ("client version is too old")
*   **Cause**: Mismatch between Traefik's default API version and Host Docker Engine.
*   **Fix**: Add `DOCKER_API_VERSION=1.45` (or higher) to Traefik environment variables in `docker-compose.yml`.

### Settings Not Saving
*   **Cause**: Frontend-Backend communication issue with unchecked checkboxes.
*   **Fix**: Already patched in `assets/view.js` and template. Clear browser cache.
