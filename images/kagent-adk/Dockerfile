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
# stalled subscribers from registration. It is written against a2a-go main;
# a2a-go-pr414.patch is that diff applied to v2.3.1 (the version kagent
# 0.10.3 pins) with one change: v2.3.1 lacks defaultInactivityTimeout, so
# defaultSubscriberTimeout is inlined as 5 * time.Minute.
#
# kagent-tool-result-cap.patch (ours, not upstream) adds an AfterToolCallback
# that truncates any tool result over KAGENT_MAX_TOOL_RESULT_CHARS, with a
# note telling the model to narrow the call. Unset = off, so the image
# behaves like stock until an agent opts in (homelab-agent.yaml). Why: one
# 327k-character GitHub_search_pull_requests result pushed a qwen session
# past its 131k context, and Ollama silently dropped the system prompt.
#
# Only /app changes. Each variant starts from the official image named by
# BASE: golang-adk:<v> for plain agents, golang-adk:<v>-full (sandbox
# runtime for skills) for agents with spec.skills. The controller derives
# both names from controller.goAgentImage in k8s/prod/kagent.
#
# DELETE THIS once a kagent release pins an a2a-go that includes #414:
# drop controller.goAgentImage from k8s/prod/kagent/kustomization.yaml and
# remove images/kagent-adk plus .github/workflows/kagent-adk-image.yaml.
# Until then a kagent bump needs KAGENT_VERSION and A2A_VERSION updated
# here (A2A_VERSION = the a2a-go/v2 version in kagent's go/go.mod), the
# patch re-checked, and the tag in kustomization.yaml updated by hand.
ARG KAGENT_VERSION=0.10.3
# Tag suffix: <KAGENT_VERSION>-<PATCHES>. Change it whenever the patch set
# changes, or nodes with the old tag cached (IfNotPresent) keep running it.
ARG PATCHES=a2a414-cap
ARG A2A_VERSION=2.3.1
ARG BASE=ghcr.io/kagent-dev/kagent/golang-adk:${KAGENT_VERSION}

FROM --platform=$BUILDPLATFORM golang:1.27-bookworm AS build
ARG KAGENT_VERSION
ARG A2A_VERSION
ARG TARGETARCH
WORKDIR /src
RUN git clone -q --depth 1 --branch v${A2A_VERSION} https://github.com/a2aproject/a2a-go.git a2a \
 && git clone -q --depth 1 --branch v${KAGENT_VERSION} https://github.com/kagent-dev/kagent.git kagent
COPY a2a-go-pr414.patch kagent-tool-result-cap.patch ./
COPY wedge_test.go a2a/a2asrv/eventqueue/homelab_wedge_test.go
RUN git -C a2a apply ../a2a-go-pr414.patch \
 && git -C kagent apply ../kagent-tool-result-cap.patch
# The patched queue's own tests plus the homelab repro (wedge_test.go),
# which fails on stock a2a-go. Native arch: this stage runs on BUILDPLATFORM.
RUN cd a2a && go test -race -count=1 ./a2asrv/eventqueue/... ./internal/taskexec/...
WORKDIR /src/kagent/go
RUN go mod edit -replace github.com/a2aproject/a2a-go/v2=/src/a2a \
 && go test -count=1 ./adk/pkg/a2a/... ./adk/pkg/agent/...
# Mirrors kagent's own build (go/Dockerfile): static, no CGO.
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build -trimpath \
      -ldflags "-s -w -X github.com/kagent-dev/kagent/go/core/internal/version.Version=${KAGENT_VERSION}-a2a414" \
      -o /app ./adk/cmd

FROM ${BASE}
LABEL org.opencontainers.image.source=https://github.com/myoung34/homelab
COPY --from=build /app /app
