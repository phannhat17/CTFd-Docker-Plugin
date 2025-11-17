# CTFd Docker Plugin - ctfcli Integration Guide

This guide explains how to use the CTFd Docker Plugin with ctfcli for streamlined challenge management.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Template Structure](#template-structure)
- [Configuration Reference](#configuration-reference)
- [Examples](#examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

The CTFd Docker Plugin now includes ctfcli templates that make it easy to:

- **Create** Docker challenges using a standard template
- **Configure** challenges with YAML files
- **Build** Docker images with provided scripts
- **Deploy** challenges to CTFd via command line
- **Manage** challenge lifecycle (create, update, sync)

## Quick Start

### 1. Prerequisites

```bash
# Install ctfcli
pip install ctfcli

# Verify installation
ctf --help
```

### 2. Initialize CTF Project

```bash
# Create a new CTF project
mkdir my-ctf
cd my-ctf
ctf init

# Enter your CTFd instance details when prompted:
# - CTFd URL: https://your-ctfd-instance.com
# - Access Token: [your-admin-token]
```

### 3. Create Your First Docker Challenge

```bash
# Copy the template
cp -r /path/to/CTFd-Docker-Plugin/ctfcli-template/docker/default ./challenges/my-first-challenge

# Navigate to the challenge
cd challenges/my-first-challenge

# Customize the challenge
vim challenge.yml
```

### 4. Build and Deploy

```bash
# Build the Docker image
./build.sh

# Deploy to CTFd
ctf challenge install

# The challenge is now live on your CTFd instance!
```

## Template Structure

The template includes everything you need to create a Docker challenge:

```
docker/default/
├── challenge.yml          # Challenge configuration (edit this!)
├── Dockerfile            # Docker image definition
├── build.sh             # Automated build script
├── flag.txt             # Flag file (can be static or dynamic)
├── cookiecutter.json    # Template variables
├── .gitignore          # Git ignore rules
├── src/                # Source code directory
│   └── challenge.c     # Example vulnerable program
├── dist/               # Built files for distribution
│   └── challenge       # Compiled binary (created by build.sh)
├── solution/           # Solution and writeup
│   └── exploit.py      # Example exploit script
└── README.md           # Template documentation
```

## Configuration Reference

### Basic Challenge Configuration

```yaml
name: "Challenge Name"
author: "Your Name"
category: "Pwn"  # Or Web, Crypto, Reverse, Misc, etc.
description: |
  Multi-line challenge description.
  Supports Markdown formatting.

type: container  # REQUIRED for Docker challenges

value: 100  # Points (or initial value if using dynamic scoring)
```

### Docker Configuration

```yaml
extra:
  # === REQUIRED ===
  image: "dockerhub-user/challenge-name:tag"
  port: 1337
  connection_type: "tcp"  # tcp, http, https, or ssh

  # === OPTIONAL ===
  command: ""  # Override Dockerfile CMD
  volumes: ""  # Comma-separated volume mounts
```

### Connection Types

#### TCP Service (Pwn/Network Challenges)

```yaml
extra:
  port: 1337
  connection_type: "tcp"
```

**Players connect with:** `nc ctfd.example.com 12345`

#### HTTP Service (Web Challenges)

```yaml
extra:
  port: 80
  connection_type: "http"
```

**Players access:** `http://ctfd.example.com:12345`

#### HTTPS Service (Secure Web Challenges)

```yaml
extra:
  port: 443
  connection_type: "https"
```

**Players access:** `https://ctfd.example.com:12345`

#### SSH Service (Linux Challenges)

```yaml
extra:
  port: 22
  connection_type: "ssh"
  ssh_username: "ctfplayer"
  ssh_password: "challenge_password_123"
```

**Players connect with:** `ssh ctfplayer@ctfd.example.com -p 12345`

### Dynamic Scoring

```yaml
extra:
  initial: 500    # Starting point value
  minimum: 100    # Minimum point value (floor)
  decay: 75       # Decay rate (higher = slower decay)
```

Points decrease as more teams solve the challenge, encouraging early solves.

### Dynamic Flags

```yaml
extra:
  flag_mode: "random"         # "static" or "random"
  random_flag_length: 32      # Length of generated flag
  flag_prefix: "flag{"        # Prefix (default: "")
  flag_suffix: "}"            # Suffix (default: "")
```

**Example generated flag:** `flag{a7b3c9d2e1f4g8h6i5j2k9l3m7n1o4p8}`

Each team/user gets a unique flag, preventing flag sharing.

### Flags, Files, and Hints

```yaml
# Static flags
flags:
  - flag{example_flag}
  - type: static
    content: flag{alternative_flag}
    data: case_insensitive

# Files for download
files:
  - dist/challenge_binary
  - handout.zip

# Hints
hints:
  - content: "Look for buffer overflows"
    cost: 0
  - content: "Check the authentication function"
    cost: 50

# Tags and topics
tags:
  - binary-exploitation
  - buffer-overflow

topics:
  - Memory Corruption
  - x86 Assembly
```

## Examples

### Example 1: Simple TCP Pwn Challenge

```yaml
name: "Buffer Overflow 101"
author: "Your Team"
category: "Pwn"
description: "Basic buffer overflow challenge. Connect and exploit the service!"
type: container
value: 100

extra:
  image: "yourteam/buffer-overflow-101:latest"
  port: 1337
  connection_type: "tcp"

flags:
  - flag{buffer_0verfl0w_basics}

files:
  - dist/vuln_binary

hints:
  - content: "The buffer is 64 bytes"
    cost: 0
```

### Example 2: Web Challenge with Dynamic Scoring

```yaml
name: "SQL Injection Portal"
author: "Your Team"
category: "Web"
description: "Can you bypass the login?"
type: container
value: 300

extra:
  image: "yourteam/sql-injection:latest"
  port: 80
  connection_type: "http"
  initial: 500
  minimum: 100
  decay: 50

flags:
  - flag{sql_1nj3ct10n_m4st3r}
```

### Example 3: SSH Challenge with Dynamic Flags

```yaml
name: "Linux Privilege Escalation"
author: "Your Team"
category: "Misc"
description: "SSH into the server and escalate privileges to read the flag."
type: container
value: 400

extra:
  image: "yourteam/privesc-challenge:latest"
  port: 22
  connection_type: "ssh"
  ssh_username: "lowpriv"
  ssh_password: "password123"
  flag_mode: "random"
  random_flag_length: 32
  flag_prefix: "flag{"
  flag_suffix: "}"

files:
  - hints/enumeration_script.sh
```

## Best Practices

### 1. Docker Images

- **Use specific tags** instead of `latest` in production
- **Keep images small** - use Alpine Linux base images when possible
- **Run as non-root user** for security
- **Test locally** before deploying to CTFd

```dockerfile
# Good practice
FROM alpine:3.18
RUN adduser -D ctfplayer
USER ctfplayer
```

### 2. Challenge Configuration

- **Set reasonable resource limits** (the plugin applies defaults)
- **Use dynamic flags** for multi-user CTFs to prevent sharing
- **Provide clear descriptions** with connection instructions
- **Include downloadable files** when appropriate

### 3. Building Images

```bash
# Tag with version
docker build -t myteam/challenge:v1.0 .

# Push to registry
docker push myteam/challenge:v1.0

# Update challenge.yml
# extra:
#   image: "myteam/challenge:v1.0"
```

### 4. Testing Workflow

```bash
# 1. Build locally
./build.sh

# 2. Test the Docker container
docker run -p 1337:1337 --name test-challenge challenge:latest

# 3. Test connectivity
nc localhost 1337

# 4. Verify the exploit works
python3 solution/exploit.py

# 5. Clean up
docker stop test-challenge
docker rm test-challenge

# 6. Deploy to CTFd
ctf challenge install
```

### 5. Version Control

```bash
# Initialize git in your CTF project
git init
git add .
git commit -m "Initial commit"

# Track challenge changes
git add challenges/my-challenge/
git commit -m "Add buffer overflow challenge"

# Use branches for different CTF events
git checkout -b ctf-2024-spring
```

## Troubleshooting

### Issue: Challenge won't install

**Error:** `Failed to install challenge`

**Solutions:**
1. Verify your CTFd URL and access token in `.ctf/config`
2. Check that `type: container` is set in challenge.yml
3. Ensure the CTFd Docker Plugin is installed and enabled
4. Check CTFd logs for specific errors

### Issue: Container won't start

**Error:** `Failed to create container`

**Solutions:**
1. Verify the Docker image exists: `docker images | grep challenge`
2. Check image is accessible from CTFd host
3. Test image locally: `docker run -p 1337:1337 image:tag`
4. Check CTFd Docker settings at `/containers/settings`

### Issue: Can't connect to container

**Error:** `Connection refused`

**Solutions:**
1. Verify `port` in challenge.yml matches Dockerfile `EXPOSE`
2. Check service is listening: `docker exec <container> netstat -ln`
3. Ensure correct `connection_type` is set
4. Check firewall rules on CTFd host

### Issue: Dynamic flags not working

**Error:** Flags aren't unique per team/user

**Solutions:**
1. Verify `flag_mode: "random"` in challenge.yml
2. Check random_flag_length is set
3. Ensure your application reads the flag from the correct location
4. Check CTFd logs for flag generation errors

### Issue: Build script fails

**Error:** `gcc: command not found` or similar

**Solutions:**
1. Install build dependencies: `apt-get install build-essential`
2. Use Docker to build: `docker run --rm -v $(pwd):/work gcc gcc ...`
3. Modify build.sh for your environment
4. Check file permissions: `chmod +x build.sh`

## Advanced Topics

### Custom Dockerfile

You can completely customize the Dockerfile for your needs:

```dockerfile
FROM python:3.11-alpine

# Install dependencies
RUN pip install flask

# Add challenge files
WORKDIR /app
COPY src/ /app/

# Expose port
EXPOSE 5000

# Run application
CMD ["python", "app.py"]
```

### Environment Variables

Pass runtime configuration through environment variables:

```dockerfile
ENV FLAG_FILE=/flag.txt
ENV TIMEOUT=300
```

The CTFd Docker Plugin may inject variables for dynamic flags.

### Multiple Services

For complex challenges, consider Docker Compose (requires additional setup):

```yaml
# docker-compose.yml
version: '3'
services:
  web:
    build: ./web
    ports:
      - "80:80"
  database:
    image: mysql:8
    environment:
      MYSQL_ROOT_PASSWORD: secret
```

### Automatic Cleanup

Containers are automatically stopped after a timeout (configurable in plugin settings).

## Resources

- [ctfcli Documentation](https://github.com/CTFd/ctfcli)
- [CTFd Documentation](https://docs.ctfd.io/)
- [Docker Documentation](https://docs.docker.com/)
- [CTFd Docker Plugin Repository](https://github.com/phannhat17/CTFd-Docker-Plugin)
- [Challenge Template README](ctfcli-template/docker/default/README.md)

## Support

If you encounter issues:

1. Check this guide and the template README
2. Review CTFd and Docker logs
3. Test your Docker image independently
4. Open an issue on GitHub with:
   - CTFd version
   - Plugin version
   - Error messages
   - challenge.yml configuration

---

**Happy Challenge Creating!** 🚩
