#!/bin/sh

# This script starts both Nginx and Uvicorn.

# Start the mariadmin dev server in the background
# Navigate to the mariadmin directory first
cd mariadmin && npm run dev &

# Start Nginx in the background.
# The `&` symbol runs the command in a subshell in the background,
# allowing the script to continue to the next command.
nginx &

# Start Uvicorn in the foreground.
# The `exec` command replaces the current shell process with the Uvicorn process.
# This is important because it ensures that signals (like SIGTERM from Docker)
# are directly passed to Uvicorn, allowing for graceful shutdown.
exec uvicorn api:app --host 0.0.0.0 --port 8000
