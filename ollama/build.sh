#!/usr/bin/env bash
# Build one Modelfile on every backend in the Ollama pool.
#
# A model has to exist on all four backends or the proxy's round-robin sends
# some analyses to a backend that doesn't have it. `ollama create` is cheap —
# it reuses the base model's blobs and writes only a new manifest — so
# rebuilding everywhere costs almost nothing.
#
# Usage: ./build.sh kotakneo-128k.Modelfile [name]
#        name defaults to the Modelfile's basename without the extension.
set -euo pipefail

modelfile=${1:?usage: build.sh <Modelfile> [name]}
name=${2:-$(basename "$modelfile" .Modelfile)}
backends=(ollama-pool-a ollama-pool-b ollama-pool-c ollama-pool-d)

for backend in "${backends[@]}"; do
  docker exec -i "$backend" sh -c "cat > /tmp/${name}.Modelfile" < "$modelfile"
  # ollama create draws its progress on stderr; only the failure matters here.
  docker exec "$backend" ollama create "$name" -f "/tmp/${name}.Modelfile" >/dev/null 2>&1
  echo "$backend: created $name"
done

echo
echo "Loaded placement (want 100% GPU — a CPU split means the context is too large):"
docker exec "${backends[0]}" sh -c "ollama run '$name' hi >/dev/null 2>&1; ollama ps"
