# Stock Ollama with two patches. First, ollama/ollama#18433, which makes the
# qwen3-coder renderer write a tool's extra JSON-schema keys in a stable
# order. Stock v0.40.3 ranges over a Go map there (Go randomizes map order),
# so kagent's 143 tools render differently on every request: 20 renders of
# the same tool list gave 20 different prompts. llama-server's prompt cache
# keys on the rendered text, so qwen re-read all ~128k tokens on every agent
# turn (~130s each) instead of only the new ones.
#
# Only the Go `ollama` binary changes. llama-server and its ROCm libraries
# come unchanged from the official image named by BASE. Only qwen
# (ollama.yaml) needs it: bonsai's qwen3.5 renderer JSON-marshals tools and
# was already stable (1 distinct render of 20).
#
# Second, context-shift.patch (ours, not upstream): OLLAMA_CONTEXT_SHIFT=false
# stops Ollama passing --context-shift to llama-server. With it, a request
# that fills num_ctx makes llama-server keep only the first 4 tokens, drop
# the next 65533 (system prompt and the user's request with them) and keep
# generating. On 2026-10-19/20 that happened 45 times in long homelab-agent
# turns, and qwen, with no instructions left, opened a PR of invented Talos
# config (#2263). Shift can only be turned off per request on the native
# API (`shift`); kagent uses /v1/chat/completions, which has no such field.
# Off, a full context is an error the agent sees instead of silent amnesia.
#
# DELETE THIS once an Ollama release includes #18433 and a server-wide way
# to turn context shift off: point ollama.yaml back at the official
# ollama/ollama:<version>-rocm image and remove images/ollama plus
# .github/workflows/ollama-image.yaml. Until then Renovate can't bump
# qwen's Ollama: bump OLLAMA_VERSION here, check the patches still apply,
# and update the tag in ollama.yaml by hand.
ARG OLLAMA_VERSION=0.40.3
ARG BASE=ollama/ollama:${OLLAMA_VERSION}-rocm

FROM golang:1.27-bookworm AS build
ARG OLLAMA_VERSION
WORKDIR /src
RUN git clone --depth 1 --branch v${OLLAMA_VERSION} https://github.com/ollama/ollama.git .
COPY 18433.patch context-shift.patch ./
RUN git apply 18433.patch && git apply context-shift.patch
RUN go test -count=1 -run 'TestResolveContextShift' ./server
# Mirrors the official build (Dockerfile `build` stage): CGO on, PIE,
# stripped. bookworm's glibc (2.36) is older than the runtime image's
# Ubuntu 24.04 (2.39), so the binary runs there.
ENV CGO_ENABLED=1
RUN go build -trimpath -buildmode=pie \
      -ldflags "-w -s -X=github.com/ollama/ollama/version.Version=${OLLAMA_VERSION}-pr18433-noshift" \
      -o /ollama .

FROM ${BASE}
LABEL org.opencontainers.image.source=https://github.com/myoung34/homelab
COPY --from=build /ollama /usr/bin/ollama
