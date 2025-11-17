# Example Dockerfile for CTFd Docker Container Challenge
# This creates a simple TCP service challenge

FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    socat \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for running the challenge
RUN useradd -m -s /bin/bash ctfplayer

# Set working directory
WORKDIR /home/ctfplayer

# Copy challenge files
# For a compiled binary challenge:
COPY src/challenge /home/ctfplayer/challenge
# For a script-based challenge:
# COPY src/server.py /home/ctfplayer/server.py

# Copy the flag file
# The CTFd plugin can inject flags dynamically if configured
COPY flag.txt /home/ctfplayer/flag.txt

# Set permissions
RUN chown -R root:root /home/ctfplayer && \
    chmod 755 /home/ctfplayer/challenge && \
    chmod 444 /home/ctfplayer/flag.txt

# Expose the service port (must match the port in challenge.yml)
EXPOSE 1337

# Switch to non-root user
USER ctfplayer

# Start the service using socat
# This wraps the challenge binary and serves it over TCP
CMD ["socat", "-T60", "TCP-LISTEN:1337,reuseaddr,fork", "EXEC:/home/ctfplayer/challenge"]

# Alternative CMD examples:
# For a Python web server:
# CMD ["python3", "-m", "http.server", "8080"]
#
# For a custom script:
# CMD ["python3", "server.py"]
#
# For an SSH server (requires additional setup):
# CMD ["/usr/sbin/sshd", "-D"]
