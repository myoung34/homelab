# Stock kagent Go agent runtime with one fix: a2aproject/a2a-go#414, for
# a2aproject/a2a-go#395. In a2a-go's in-memory event queue, a streaming
# subscriber that stops reading (client still connected, TCP window full)
# parks the task's broker goroutine forever. Any later subscriber to that
# task then blocks inside the queue manager's process-wide mutex, so no new
# task can start anywhere in the pod, and the detached execution context
# means nothing ever recovers. On 2026-10-14 this wedged homelab-agent for
# eight hours: every chat hung 300s with no Execute log until a restart.
#
# #414 bounds how long the broker waits on one subscriber (5m) and isolates
# stalled subscribers from registration. a2a-go-pr414.patch is #414's diff,
# unmodified, applied to a2a-go v2.5.0 (the version kagent 0.10.5 pins;
# stock kagent 0.10.3 pinned v2.3.1).
#
# But kagent 0.10.3 links two a2a-go modules, and its A2A server (a2asrv,
# taskexec, eventqueue) runs on the old one, github.com/a2aproject/a2a-go
# v0.3.15, which #414 does not touch. On 2026-10-15 homelab-agent wedged the
# same way with #414 applied; the goroutine dump showed only a2a-go@v0.3.15
# frames. a2a-go-v0-stalled-subscriber.patch (ours; #414 targets main only)
# is the minimal v0 fix: the broker gives each subscriber 5m to accept an
# event, then closes and drops it. wedge_v0_test.go is its repro.
#
# Both a2a-go versions are pinned: the build fails if kagent's go.mod stops
# requiring exactly A2A_VERSION / A2A_V0_VERSION, and if /app was not linked
# against the patched trees. Renovate holds the kagent charts at 0.10.3
# (renovate.json) for the same reason.
#
# kagent-pr2791.patch is kagent-dev/kagent#2791 (open backport to
# release/v0.10.x of #2790, merged on main): the Go runtime honours
# spec.declarative.context.compaction, which stock 0.10.3 ignores. Agent code
# only: #2791 also bumped google.golang.org/adk/v2 2.1.0 -> 2.3.0 (which
# carries session/compaction) and a2a-go/v2 2.3.1 -> 2.5.0, but kagent 0.10.5
# (kagent-dev/kagent#3522) ships both, so the go.mod/go.sum hunks are
# dropped here; they no longer apply. The 0.10.3
# controller already writes the compaction settings into the agent config;
# it just labels them "ignored" in the UnsupportedFeatures condition.
#
# kagent-tool-result-cap.patch (ours, not upstream) adds an AfterToolCallback
# that truncates any tool result over KAGENT_MAX_TOOL_RESULT_CHARS, with a
# note telling the model to narrow the call. Unset = off, so the image
# behaves like stock until an agent opts in (homelab-agent.yaml). Why: one
# 327k-character GitHub_search_pull_requests result pushed a qwen session
# past its 131k context, and Ollama silently dropped the system prompt.
#
# kagent-fail-inflight-on-shutdown.patch (ours, not upstream) marks a turn
# failed when the pod is stopped mid-turn. Stock kagent exits on SIGTERM
# with the task still "working" in the controller, and the UI then refuses
# every new message in that chat ("This session is already being
# processed") forever. On 2026-10-15 two ArgoCD rollouts of homelab-agent
# bricked two chats this way. The task store now remembers unfinished
# tasks, and after the HTTP server's shutdown timeout it saves them as
# failed with a "send your message again" note and rejects late saves.
#
# kagent-skills-init-reentrant.patch (ours; upstream's #2655 for #2646 went
# stale) makes skills-init clear a destination before cloning into it. A
# restarted init container finds the last attempt's clones on the pod's
# emptyDir and `git clone` refuses a non-empty directory, so one stalled
# GitHub clone left homelab-agent in Init:CrashLoopBackOff for 32h
# (2026-10-19, "destination path '/skills/ponytail' already exists").
# Built as a second image, ghcr.io/myoung34/homelab/skills-init (target
# skills-init below), from the official skills-init:<v> with only the
# binary replaced; controller.skillsInitImage points at it.
#
# kagent-bash-timeout.patch (ours, not upstream) reads
# KAGENT_BASH_TIMEOUT_SECONDS for the skills bash tool: unset keeps stock's
# 30s (60s if the command mentions python), a positive value replaces both,
# and 0 turns the timeout off; the bash tool description tells the model
# which applies. Stock 0.10.3 hardcodes 30s and has no per-call override
# (kagent main added timeout_seconds later). Session
# 01a159bc-f8be-78d5-83c3-6236e046ff8c (Talos 1.14.2) lost its first repo
# tarball to it mid-extract, then spent ~40 turns on the half-extracted
# tree; terraform init in terraform/talos/validate.sh does not fit in 30s
# either.
#
# adk-go-reconfirm-on-resume.patch is the core of google/adk-go#2238 (open,
# for #2233) cut down to v2.3.0, the adk-go kagent 0.10.6 pins; #2238
# itself targets main and does not apply. When a tool resumed after a
# human answer asks for confirmation again, stock adk-go records the
# request but never emits the adk_request_confirmation, so the client
# never sees it. kagent's remote agent tool does exactly that whenever a
# subagent pauses a second time: on 2026-11-18 homelab-agent's follow-up
# ask_user (immich, session 01a1ebfb-633c) reached router-agent as a bare
# {"status":"pending"}, the router told Mark "I'll relay the findings", and
# the task completed with homelab-agent still waiting. reconfirm_test.go is
# the repro. kagent v1.0.1 (adk v2.6.0) does not have the fix either.
#
# Each variant starts from the official image named by BASE:
# golang-adk:<v> for plain agents, golang-adk:<v>-full (sandbox runtime for
# skills) for agents with spec.skills. The controller derives both names
# from controller.goAgentImage in k8s/prod/kagent. The plain variant only
# replaces /app. The -full variant (target full) also adds tesseract, so
# agents can read images Mark sends (image links, or Slack uploads through
# the kagent-slack-bridge file proxy): curl the image, `tesseract <file> -`.
# The models are text-only, and every agent here runs -full.
#
# DELETE THIS once a kagent release runs its server on an a2a-go that
# includes #414 (or a v0 equivalent), then drop the renovate.json hold:
# drop controller.goAgentImage and controller.skillsInitImage from
# k8s/prod/kagent/kustomization.yaml and
# remove images/kagent-adk plus .github/workflows/kagent-adk-image.yaml.
# Until then a kagent bump needs KAGENT_VERSION and A2A_VERSION updated
# here (A2A_VERSION = the a2a-go/v2 version in kagent's go/go.mod;
# A2A_V0_VERSION = the github.com/a2aproject/a2a-go
# version there), the patches re-checked, and the tag in
# kustomization.yaml updated by hand. Drop kagent-pr2791.patch once the
# kagent release includes #2790/#2791. ADK_VERSION = google.golang.org/adk/v2
# in kagent's go/go.mod; drop the adk-go patch once that version has #2238.
ARG KAGENT_VERSION=0.10.6
# Tag suffix: <KAGENT_VERSION>-<PATCHES>. Change it whenever the patch set
# changes, or nodes with the old tag cached (IfNotPresent) keep running it.
ARG PATCHES=a2a414v0-cap-compact-orphan-reinit-bashto-reconfirm-ocr
ARG A2A_VERSION=2.5.0
ARG A2A_V0_VERSION=0.3.15
ARG ADK_VERSION=2.3.0
ARG BASE=ghcr.io/kagent-dev/kagent/golang-adk:${KAGENT_VERSION}

FROM --platform=$BUILDPLATFORM golang:1.27-bookworm AS build
ARG KAGENT_VERSION
ARG A2A_VERSION
ARG A2A_V0_VERSION
ARG ADK_VERSION
ARG PATCHES
ARG TARGETARCH
WORKDIR /src
RUN git clone -q --depth 1 --branch v${A2A_VERSION} https://github.com/a2aproject/a2a-go.git a2a \
 && git clone -q --depth 1 --branch v${A2A_V0_VERSION} https://github.com/a2aproject/a2a-go.git a2a-v0 \
 && git clone -q --depth 1 --branch v${ADK_VERSION} https://github.com/google/adk-go.git adk \
 && git clone -q --depth 1 --branch v${KAGENT_VERSION} https://github.com/kagent-dev/kagent.git kagent
COPY a2a-go-pr414.patch a2a-go-v0-stalled-subscriber.patch adk-go-reconfirm-on-resume.patch \
     kagent-pr2791.patch kagent-tool-result-cap.patch kagent-fail-inflight-on-shutdown.patch \
     kagent-skills-init-reentrant.patch kagent-bash-timeout.patch ./
COPY wedge_test.go a2a/a2asrv/eventqueue/homelab_wedge_test.go
COPY wedge_v0_test.go a2a-v0/a2asrv/eventqueue/homelab_wedge_test.go
COPY reconfirm_test.go adk/internal/llminternal/homelab_reconfirm_test.go
RUN git -C a2a apply ../a2a-go-pr414.patch \
 && git -C a2a-v0 apply ../a2a-go-v0-stalled-subscriber.patch \
 && git -C adk apply ../adk-go-reconfirm-on-resume.patch \
 && git -C kagent apply ../kagent-pr2791.patch \
 && git -C kagent apply ../kagent-tool-result-cap.patch \
 && git -C kagent apply ../kagent-fail-inflight-on-shutdown.patch \
 && git -C kagent apply ../kagent-skills-init-reentrant.patch \
 && git -C kagent apply ../kagent-bash-timeout.patch
# The patched packages' own tests plus the homelab repros (wedge_test.go,
# wedge_v0_test.go, reconfirm_test.go), which fail on stock a2a-go/adk-go.
# Native arch: this stage runs on BUILDPLATFORM.
RUN cd a2a && go test -race -count=1 ./a2asrv/eventqueue/... ./internal/taskexec/... \
 && cd ../a2a-v0 && go test -race -count=1 ./a2asrv/... ./internal/taskexec/... \
 && cd ../adk && go test -count=1 ./internal/llminternal/...
WORKDIR /src/kagent/go
# Pin: a patch only helps if kagent requires the exact version it was made
# against. Fail here rather than ship an unpatched server.
RUN test "$(go list -m -f '{{.Version}}' github.com/a2aproject/a2a-go/v2)" = "v${A2A_VERSION}" \
 && test "$(go list -m -f '{{.Version}}' github.com/a2aproject/a2a-go)" = "v${A2A_V0_VERSION}" \
 && test "$(go list -m -f '{{.Version}}' google.golang.org/adk/v2)" = "v${ADK_VERSION}" \
 && go mod edit -replace github.com/a2aproject/a2a-go/v2=/src/a2a \
      -replace github.com/a2aproject/a2a-go=/src/a2a-v0 \
      -replace google.golang.org/adk/v2=/src/adk \
 && go test -count=1 ./adk/pkg/a2a/... ./adk/pkg/agent/... ./adk/pkg/runner/... \
      ./adk/pkg/app/... ./adk/pkg/taskstore/... ./core/internal/skillsinit/... \
 && go test -short -count=1 ./adk/pkg/skills/... ./adk/pkg/tools/...
# Mirrors kagent's own build (go/Dockerfile): static, no CGO.
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -trimpath \
      -ldflags "-s -w -X github.com/kagent-dev/kagent/go/core/internal/version.Version=${KAGENT_VERSION}-${PATCHES}" \
      -o /app ./adk/cmd \
 && go version -m /app | grep -A1 -E 'dep\s+github.com/a2aproject/a2a-go\s' | grep -q '=>\s/src/a2a-v0\s' \
 && go version -m /app | grep -A1 -E 'dep\s+github.com/a2aproject/a2a-go/v2\s' | grep -q '=>\s/src/a2a\s' \
 && go version -m /app | grep -A1 -E 'dep\s+google.golang.org/adk/v2\s' | grep -q '=>\s/src/adk\s'
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -trimpath -ldflags "-s -w" \
      -o /skills-init ./core/cmd/skills-init

FROM ghcr.io/kagent-dev/kagent/skills-init:${KAGENT_VERSION} AS skills-init
LABEL org.opencontainers.image.source=https://github.com/myoung34/homelab
COPY --from=build /skills-init /usr/local/bin/skills-init

FROM ${BASE} AS agent
LABEL org.opencontainers.image.source=https://github.com/myoung34/homelab
COPY --from=build /app /app

# -full only: the plain base has no package manager. Wolfi (the -full base)
# keeps only current package versions, so these are unpinned.
FROM agent AS full
USER 0
RUN apk add --no-cache tesseract tesseract-eng
USER 1001:1001

# Last stage, so the default build target stays the plain agent image.
FROM agent
