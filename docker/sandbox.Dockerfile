# PlanD sandbox image for the docker execution backend: Python 3.11 + git + common CLI tools.
# Built automatically by DockerBackend the first time it is needed (tag pland-sandbox:py3.11).
FROM python:3.11-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates jq less procps \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest requests beautifulsoup4 pyyaml
RUN git config --system user.name "pland-agent" && git config --system user.email "agent@pland.local" \
 && git config --system init.defaultBranch main && git config --system --add safe.directory '*'
WORKDIR /workspace
