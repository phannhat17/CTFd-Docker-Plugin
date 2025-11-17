#!/bin/bash
# Build script for the Docker challenge

# Exit on error
set -e

echo "[*] Building challenge binary..."
gcc src/challenge.c -o src/challenge -fno-stack-protector -no-pie -m32
echo "[+] Challenge binary built successfully!"

echo "[*] Building Docker image..."
docker build -t example-docker-challenge:latest .
echo "[+] Docker image built successfully!"

echo "[*] Creating distributable files..."
mkdir -p dist
cp src/challenge dist/challenge
echo "[+] Distributable files created in dist/"

echo ""
echo "=== Build Complete ==="
echo "Docker image: example-docker-challenge:latest"
echo "Distributable: dist/challenge"
echo ""
echo "Next steps:"
echo "1. Update challenge.yml with your Docker image name"
echo "2. Update flags in challenge.yml"
echo "3. Run 'ctf challenge install' to deploy to CTFd"
