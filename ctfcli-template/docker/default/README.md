# Docker Container Challenge Template

This template is designed for creating Docker-based CTF challenges that work with the CTFd-Docker-Plugin and ctfcli.

## Quick Start

1. **Copy this template:**
   ```bash
   ctf challenge add --templates /path/to/CTFd-Docker-Plugin/ctfcli-template
   ctf challenge new docker
   ```

2. **Customize your challenge:**
   - Edit `src/challenge.c` (or add your own challenge files)
   - Update `challenge.yml` with your challenge details
   - Modify `Dockerfile` if needed for your specific requirements

3. **Build your challenge:**
   ```bash
   ./build.sh
   ```

4. **Test locally:**
   ```bash
   docker run -p 1337:1337 example-docker-challenge:latest
   # In another terminal:
   nc localhost 1337
   ```

5. **Deploy to CTFd:**
   ```bash
   ctf challenge install
   ```

## Directory Structure

```
.
├── challenge.yml       # CTFd challenge configuration
├── Dockerfile          # Docker image definition
├── build.sh           # Build script
├── flag.txt           # Challenge flag (can be dynamic)
├── src/               # Source code
│   └── challenge.c    # Example vulnerable program
├── dist/              # Distributable files (created by build.sh)
│   └── challenge      # Compiled binary for players to download
└── solution/          # Solution files (optional)
    └── exploit.py     # Example exploit script
```

## Challenge Configuration

### challenge.yml

The `challenge.yml` file contains all the configuration for your challenge:

- **Basic info:** name, author, category, description
- **Type:** Must be `container` for Docker challenges
- **Docker config:** image name, port, connection type
- **Flags:** Static or dynamic flag configuration
- **Files:** Downloadable files for players
- **Hints, tags, topics:** Optional metadata

### Docker Configuration Options

In the `extra` section of `challenge.yml`:

- `image`: Docker image name (e.g., `username/challenge:latest`)
- `port`: Internal container port (e.g., `1337`)
- `connection_type`: How players connect - `tcp`, `http`, `https`, or `ssh`
- `command`: Override container CMD (optional)
- `volumes`: Mount volumes (optional, rarely needed)

### Connection Types

#### TCP Service (most common for pwn challenges)
```yaml
extra:
  port: 1337
  connection_type: "tcp"
```
Players connect using: `nc <host> <port>`

#### HTTP/HTTPS Service (for web challenges)
```yaml
extra:
  port: 80
  connection_type: "http"
```
Players access via browser: `http://<host>:<port>`

#### SSH Service (for SSH challenges)
```yaml
extra:
  port: 22
  connection_type: "ssh"
  ssh_username: "ctfplayer"
  ssh_password: "password123"
```
Players connect using: `ssh ctfplayer@<host> -p <port>`

## Building Your Challenge

### 1. Create Your Challenge Binary/Service

Edit `src/challenge.c` or add your own files:

```bash
# Compile a binary challenge
gcc src/challenge.c -o src/challenge -fno-stack-protector -no-pie

# Or for Python/Node.js services, just add your files to src/
```

### 2. Build Docker Image

```bash
./build.sh
# Or manually:
docker build -t your-image-name:latest .
```

### 3. Update challenge.yml

Update the `image` field in `challenge.yml`:
```yaml
extra:
  image: "your-dockerhub-username/your-image-name:latest"
```

### 4. Push to Docker Registry (if using remote repository)

```bash
docker tag your-image-name:latest your-dockerhub-username/your-image-name:latest
docker push your-dockerhub-username/your-image-name:latest
```

## Dynamic Flags

The CTFd-Docker-Plugin supports per-user/per-team flag generation:

```yaml
extra:
  flag_mode: "random"
  random_flag_length: 32
  flag_prefix: "flag{"
  flag_suffix: "}"
```

To use dynamic flags in your container, the plugin will inject the flag through environment variables or a mounted file.

## Dynamic Scoring

Enable dynamic scoring to decrease points as more teams solve:

```yaml
extra:
  initial: 500    # Starting points
  minimum: 100    # Minimum points
  decay: 75       # Decay rate (higher = slower)
```

## Testing

### Test Locally

```bash
# Run the container
docker run -p 1337:1337 your-image-name:latest

# In another terminal, connect to it
nc localhost 1337
```

### Test on CTFd

```bash
# Install to CTFd
ctf challenge install

# Check the challenge page
# Start a container and test the connection
```

## Tips

1. **Keep images small:** Use Alpine Linux base images when possible
2. **Security:** Run services as non-root user
3. **Resource limits:** The plugin applies memory/CPU limits automatically
4. **Timeouts:** Containers have automatic timeout/cleanup
5. **Port conflicts:** Each user gets unique port mappings
6. **Flag files:** Can be injected dynamically by the plugin

## Common Issues

### Image not found
- Make sure the image is built and available on the Docker host
- If using a registry, ensure it's pushed: `docker push image:tag`

### Connection refused
- Check the port in `challenge.yml` matches the EXPOSE port in Dockerfile
- Verify the service is actually listening (check container logs)

### Permission denied
- Ensure the challenge binary/script has execute permissions
- Check file ownership in the Dockerfile

## Example Challenges

See the `src/` directory for example challenge types:
- Binary exploitation (buffer overflow)
- Web services (Flask, Express)
- Cryptography services
- SSH-based challenges

## Resources

- [CTFd Documentation](https://docs.ctfd.io/)
- [ctfcli Documentation](https://github.com/CTFd/ctfcli)
- [CTFd-Docker-Plugin](https://github.com/phannhat17/CTFd-Docker-Plugin)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
