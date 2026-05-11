# Builder image for the qudrat-bot project. Mirrors qudrat.ai's builder
# (same Go + tool versions) so a single host cache serves both.
FROM docker.io/library/golang:1.26.2-alpine

ARG GOLANGCI_LINT_VERSION=v2.5.0
ARG GOFUMPT_VERSION=v0.8.0

RUN apk add --no-cache bash curl git make tar build-base

RUN go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}" && \
    go install "mvdan.cc/gofumpt@${GOFUMPT_VERSION}"

ENV CGO_ENABLED=0 \
    GOFLAGS="-buildvcs=false" \
    GOTOOLCHAIN=local

WORKDIR /work
