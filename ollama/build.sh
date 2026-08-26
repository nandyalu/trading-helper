#!/usr/bin/env bash
# Build one Modelfile into the Ollama pool.
#
# Every pool container bind-mounts the *same* host directory at
# /root/.ollama/models, so a model created through any one of them is
# immediately visible to all of them. Building once is enough.
#
# This script used to loop over a hardcoded a..d, which was wasteful rather
# than wrong — it wrote the same manifest seven times into one directory. The
# note in CLAUDE.md that a model could end up on some backends and not others,
# failing that share of runs, described a failure the shared mount makes
# impossible. It is gone.
#
# The loop is kept only as a *check*: build on one, then confirm every running
# backend can see it. That costs one `ollama list` each and catches the day
# somebody gives a container its own models volume.
set -euo pipefail

modelfile=${1:?usage: build.sh <Modelfile> [name]}
name=${2:-$(basename "$modelfile" .Modelfile)}
mapfile -t backends < <(docker ps --format '{{.Names}}' | grep -E '^ollama-pool-' | sort)
if [ ${#backends[@]} -eq 0 ]; then
  echo "No running ollama-pool-* containers found." >&2
  exit 1
fi

builder=${backends[0]}
docker exec -i "$builder" sh -c "cat > /tmp/${name}.Modelfile" < "$modelfile"
# ollama create draws its progress on stderr; only the failure matters here.
docker exec "$builder" ollama create "$name" -f "/tmp/${name}.Modelfile" >/dev/null 2>&1
echo "$builder: created $name (shared models directory)"
echo

missing=0
for backend in "${backends[@]}"; do
  if docker exec "$backend" ollama list 2>/dev/null | awk '{print $1}' | grep -qx "${name}:latest"; then
    echo "  $backend: sees it"
  else
    echo "  $backend: MISSING — does it have its own models volume?" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo >&2
  echo "A backend that cannot see the model fails its share of analyses." >&2
  exit 1
fi

echo
echo "Loaded placement (want 100% GPU — a CPU split means the context is too large):"
docker exec "${backends[0]}" sh -c "ollama run '$name' hi >/dev/null 2>&1; ollama ps"
