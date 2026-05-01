# prompter

Web game: write the shortest prompt that makes a chosen LLM reproduce a target
output. Code first; image/video/UI later. Hosted at `prompter.omarss.net`.

See `CLAUDE.md` for stack, conventions, and build flow.

## Quickstart

```sh
make builder   # build the local builder image (one-time)
make test      # run unit tests inside the builder
make lint      # static analysis
make build     # build all service binaries to bin/
make run-api   # run the api locally
```

No Go is required on the host — everything runs inside the builder container
via podman.
