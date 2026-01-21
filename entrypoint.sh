#!/bin/bash
set -e

# Ensure directories exist (in case they are not mounted)
mkdir -p newones outputs logs

# Set permissions if needed (optional, depends on host UID/GID issues)
# For now, we assume the container runs as root (default in Docker)
# so it can write to mapped volumes.

# Initialize internal database/config if needed (placeholder)

# Execute the passed command
exec "$@"
