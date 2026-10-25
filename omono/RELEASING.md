# Releasing Omono

Each checkout or Git worktree needs its own gitignored `local.properties`
inside `omono/`. Before releasing, securely provision these values from the
existing private configuration:

```properties
sdk.dir=/path/to/Android/Sdk
gplaces.api.url=https://api.omarss.net
gplaces.api.key=<existing API key>
```

Never commit the key or print it in build logs. Places, roads, quizzes, and
docs all use this URL and key. An APK built without them disables those
requests and displays empty results, even when the backend is healthy.

Run `make validate-release-config` before preparing a release. `make release`
runs this check before changing the version or creating a commit or tag.
Release builds also run it automatically, including `make assemble-release`.
Debug builds may omit credentials for local development.

Run `make test`, `make lint`, and `make assemble-release` before publishing.
Verify the release APK contains the configured API URL and key, authenticate
against the live data endpoints with those values, and confirm the signing
certificate matches the previous release so Android can install the update.

Use `make release` for the normal version, build, publish, and push flow.
Use `make publish` only for an already verified release APK. After publishing,
verify the public manifest's version, size, and SHA-256 against the downloaded
APK. Test installation on a connected Android device when one is available.
