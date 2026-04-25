# Builder image for the ivr project. All builds, tests, and lints run here.
# No Go is required on the host.
#
# Pinned tool versions are intentional — bump deliberately and verify in CI.
FROM docker.io/library/golang:1.26.2-alpine

ARG GOLANGCI_LINT_VERSION=v2.5.0
ARG GOFUMPT_VERSION=v0.8.0
ARG SQLC_VERSION=v1.30.0
ARG MIGRATE_VERSION=v4.19.0

RUN apk add --no-cache \
    bash \
    curl \
    git \
    make \
    tar \
    build-base \
    postgresql18-client

# All tools are built from source against our pinned Go toolchain.
# Building golangci-lint from source avoids "binary built with go1.X < project
# go1.Y" mismatches when a new Go release lands.
RUN go install "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}" && \
    go install "mvdan.cc/gofumpt@${GOFUMPT_VERSION}" && \
    go install "github.com/sqlc-dev/sqlc/cmd/sqlc@${SQLC_VERSION}" && \
    go install -tags 'postgres' "github.com/golang-migrate/migrate/v4/cmd/migrate@${MIGRATE_VERSION}"

ENV CGO_ENABLED=0 \
    GOFLAGS="-buildvcs=false" \
    GOTOOLCHAIN=local

WORKDIR /work
