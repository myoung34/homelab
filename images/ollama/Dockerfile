# Stock Ollama with one patch, context-shift.patch (ours, not upstream):
# OLLAMA_CONTEXT_SHIFT=false stops Ollama passing --context-shift to
# llama-server. With it, a request that fills num_ctx makes llama-server
# keep only the first 4 tokens, drop the next 65533 (system prompt and the
# user's request with them) and keep generating. On 2026-10-19/20 that
# happened 45 times in long homelab-agent turns, and qwen, with no
# instructions left, opened a PR of invented Talos config (#2263). Shift can
# only be turned off per request on the native API (`shift`); kagent uses
# /v1/chat/completions, which has no such field. Off, a full context is an
# error the agent sees instead of silent amnesia.
#
# Only the Go `ollama` binary changes. llama-server and its ROCm libraries
# come unchanged from the official image named by BASE. Only qwen
# (ollama.yaml) uses it.
#
# This image also used to carry ollama/ollama#18433 (stable tool-schema key
# order in the qwen3-coder renderer, so the prompt cache hits). v0.40.17
# ships the same fix upstream (ollama/ollama#19686), so that patch is gone.
#
# DELETE THIS once an Ollama release has a server-wide way to turn context
# shift off: point ollama.yaml back at the official
# ollama/ollama:<version>-rocm image and remove images/ollama plus
# .github/workflows/ollama-image.yaml, plus the ollama customManagers and
# packageRules in renovate.json. Until then Renovate bumps OLLAMA_VERSION
# and the tag in ollama.yaml together; if the patch stops applying, the
# ollama-image build fails and the PR stays open.
ARG OLLAMA_VERSION=0.40.17
ARG BASE=ollama/ollama:${OLLAMA_VERSION}-rocm

FROM golang:1.27-bookworm AS build
ARG OLLAMA_VERSION
WORKDIR /src
RUN git clone --depth 1 --branch v${OLLAMA_VERSION} https://github.com/ollama/ollama.git .
COPY context-shift.patch ./
RUN git apply context-shift.patch
RUN go test -count=1 -run 'TestResolveContextShift' ./server
# Mirrors the official build (Dockerfile `build` stage): CGO on, PIE,
# stripped. bookworm's glibc (2.36) is older than the runtime image's
# Ubuntu 24.04 (2.39), so the binary runs there.
ENV CGO_ENABLED=1
RUN go build -trimpath -buildmode=pie \
      -ldflags "-w -s -X=github.com/ollama/ollama/version.Version=${OLLAMA_VERSION}-noshift" \
      -o /ollama .

FROM ${BASE}
LABEL org.opencontainers.image.source=https://github.com/myoung34/homelab
COPY --from=build /ollama /usr/bin/ollama
