# workspace_personal — orientation for Claude

Monorepo of personal projects. Each top-level directory is an independent
project with its own `Makefile`; there's no cross-project build system.

## Layout

| Path          | What                                                                 |
|---------------|----------------------------------------------------------------------|
| `app2cli/`    | CLI wrapper around a desktop app (unchanged by recent work)          |
| `homelab/`    | k3s + host-nginx gitops configs for this machine                     |
| `omono/`      | Android app — Kotlin / Compose / Hilt, background speed monitor      |
| `os-doctor/`  | (untracked at time of writing — ignore unless the user mentions it)  |
| `reach_me/`   | (unchanged by recent work)                                           |
| `swet/`       | (unchanged by recent work)                                           |
| `swet_cli/`   | (unchanged by recent work)                                           |
| `tanzeel-ai/` | (unchanged by recent work)                                           |

## Machine setup

- **Native Ubuntu** (not WSL, despite stale env var history)
- Host nginx + system certbot handle TLS for every `*.omarss.net` vhost
- k3s cluster runs in-place; apps deployed via `homelab/apps/`
- SDKMAN provides the JDK toolchain (`~/.sdkman/candidates/java/`)
- Android SDK at `~/Android/Sdk` (Linux-native, set in `~/.bashrc`)

## homelab/

Gitops source of truth for the k3s cluster *and* the host nginx layer
on this machine. It is NOT auto-applied — the user runs
`sudo make -C homelab <target>` to reconcile.

### Host nginx pattern
- One `nginx/{domain}.conf` per site, stored **pre-certbot** (no `listen 443 ssl;` block)
- `make apply-nginx` copies all confs into `/etc/nginx/sites-{available,enabled}/` and reloads
- TLS is added by running `sudo certbot --nginx -d {domain}` **once per cert** — certbot injects the 443 block
- ⚠️ **Gotcha**: re-running `apply-nginx` clobbers the certbot-added 443 blocks. You must re-run `certbot --nginx -d {domain}` after every apply. Certbot reuses the cached cert, so no LE API call — but the step is mandatory or the site falls back to whichever server has the default TLS listener (`claw.omarss.net` at time of writing)
- **Known sites**: `claw.omarss.net`, `swet.omarss.net`, `sync.omarss.net`, `apps.omarss.net`

### apps.omarss.net — personal APK host
Self-hosted sideload target for Android apps via [Obtainium](https://github.com/ImranR98/Obtainium).

- Doc root: `/srv/apps/` (owned `omar:omar`, mode 755 — **critical**, see gotchas)
- Static files: `index.html`, `manifest.json`, `{app}.latest.apk`, `{app}.{version}.apk`
- `index.html` is fully dynamic: fetches `/manifest.json` on load and renders app cards client-side. Changelogs are classified by conventional-commit prefix (feat / fix / break / chore / docs / ...) with colour-coded tags
- `manifest.json` is server-owned data — **never committed to git**. It's merged in-place on each publish
- `/usr/local/bin/update-apps-manifest` is the atomic jq-based merger. Any project's publish flow can call it without depending on this repo being checked out. Installed by `scripts/setup-apps-host.sh`

### homelab Makefile targets
- `apply-nginx` — copy + reload all vhosts (requires re-running certbot, see above)
- `apply-apps-host` — idempotent: ensures `/srv/apps` 755, installs `index.html`, seeds `manifest.json`, installs `update-apps-manifest` to `/usr/local/bin`, reloads nginx. **Safe to re-run**, but clobbers certbot → re-run `sudo certbot --nginx -d apps.omarss.net` after
- `apply-obsidian`, `apply-openclaw` — k8s apps
- `apply-all` — everything

### Gotchas / known warts
1. **`apply-nginx` clobbers certbot** (documented above)
2. **`rsync -a` vs `/srv/apps` mode** — solved in `omono/scripts/publish.sh`. If you're writing a new publish script for a different app: use `-t --no-perms --no-owner --no-group` so rsync never touches the destination directory's attributes. `-a` on a staging dir will propagate `mktemp -d`'s 700 mode onto `/srv/apps` and lock nginx out with a 403
3. **`sudo umask`** — `mkdir -p` under `sudo` can inherit 077 on this machine. Use `install -d -m 755 -o omar -g omar` instead of `mkdir && chmod && chown`

## omono/

Kotlin / Jetpack Compose / Hilt Android app. Background speed monitor
with a pluggable `OmonoFeature` API — new trackers slot in as
additional Gradle modules with a single `@Binds @IntoSet` binding.

### Module layout
```
app/                     thin shell — Hilt Application, MainActivity (Compose)
build-logic/convention/  5 precompiled plugins (application/library/compose/hilt/feature)
core/common              shared domain types (SpeedUnit conversions)
core/data                single-source omonoDataStore (prefix-namespaced keys)
core/designsystem        OmonoTheme + shared composables
core/notification        channel registry + OmonoNotificationController
core/service             OmonoFeature API + FeatureRegistry + FeatureHostService
feature/speed            first feature: GPS → FeatureState via FusedLocation
```

### Toolchain pins
- **AGP 8.11.1 + Gradle 8.14.3 + Kotlin 2.2.21 + Hilt 2.57.1 + KSP 2.2.21-2.0.4**
- `org.gradle.java.home=~/.sdkman/candidates/java/21.0.10-tem` — Gradle daemon pinned to JDK 21 because Gradle 8.14 doesn't officially support the machine's default JDK 25
- **Do not bump to AGP 9.x** without testing the full matrix. As of Apr 2026, AGP 9 + Hilt + KSP + Compose + `kotlin-android` plugin do not form a working combo — AGP 9 removed `BaseExtension` which Kotlin 2.2 still references, and KSP isn't compatible with AGP 9's built-in Kotlin. Revisit only when Hilt ≥ 2.60 and KSP ≥ 2.3.7 ship stable. The full dependency hell is documented in the commit history

### Release flow
`make release` is one-shot and does everything:
1. `scripts/bump-version.sh` — parses the last `omono/v*` tag, walks conventional commits on `omono/` paths since, classifies bump (`major` / `minor` / `patch`), rewrites `app/build.gradle.kts`
2. `scripts/changelog.sh` — prints subject lines since last tag, one per line, conventional-commit prefix preserved
3. Commits the version bump as `release omono v${X.Y.Z}`
4. Tags `omono/v${X.Y.Z}`
5. `./gradlew assembleRelease`
6. `scripts/publish.sh` — rsyncs APK to `/srv/apps`, calls `update-apps-manifest` (locally or via SSH)
7. `git push origin main` + tag

Aborts if the working tree is dirty. Env overrides: `OMONO_RELEASE_HOST` (default `/srv/apps`), `OMONO_RELEASE_URL` (default `https://apps.omarss.net`).

### Signing
- Debug signing used for release builds unless `app/keystore.properties` exists (gitignored)
- `make release-keystore` generates a real keystore at `~/.android/omono-release.jks`
- Debug signing is fine for personal Obtainium use — Obtainium just needs cert stability across releases, not Play Store trust

### Tests
- `make test` — JVM + Robolectric, runs in seconds (no emulator)
- `make connected-test` — needs an adb device or emulator
- `make lint` — Android lint across all modules
- `make check` — full verification
- **KVM exists on this machine but the user is not in the `kvm` group** — emulator needs `sudo usermod -aG kvm omar` + relogin before `connected-test` can use a local emulator

### Known not-yet-done
- Compose UI tests — would need stateless/stateful refactor of `OmonoMainScreen`
- R8 / Proguard rules not validated → `isMinifyEnabled = false` in release build
- Battery optimisation for `SpeedRepository` (1 Hz GPS is heavy)
- Real-device smoke test — APK has been built and published but never installed on hardware

## Session protocol

- **Never push without committing atomic units**. `release.sh` enforces this by refusing to run on a dirty tree
- **Never re-run `apply-nginx` without also re-running certbot** for every affected domain. Or the TLS listener disappears silently
- **Never `chmod` / `chown` system paths without asking** unless the fix is obviously local to the user's own files (e.g. `/srv/apps` is owned by `omar`, so chmod is fine without sudo)
- **Manifests (Android, k8s, nginx, JSON schema for the apps host) are git-tracked**. `/srv/apps/manifest.json` is the only "manifest" that is *not* tracked — it's runtime state on the host, regenerated on every publish
- When in doubt about pins or ecosystem compat, the commit history has the "why" — prefer reading it over guessing
