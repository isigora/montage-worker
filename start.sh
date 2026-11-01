#!/bin/sh
set -e
# Keep productions and agent sessions on the persistent volume.
mkdir -p "$DATA_DIR/projects" "$DATA_DIR/jobs" "$CLAUDE_CONFIG_DIR"
if [ ! -L "$OM_DIR/projects" ]; then
  rm -rf "$OM_DIR/projects"
  ln -s "$DATA_DIR/projects" "$OM_DIR/projects"
fi
cd /app
exec uvicorn worker.app:app --host :: --port "${PORT:-8080}"
