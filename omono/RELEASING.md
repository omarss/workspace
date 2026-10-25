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

## Fajr alarm verification

The loud athan is Fajr only. The Prayer screen's **Alarm checks** panel shows
exact-alarm access, notification access, DND alarm restrictions, current alarm
volume, the next scheduled time, and durable delivery/audio checkpoints.
**Repair and check alarms** rebuilds the next occurrence of every prayer from
saved location and current settings. Today and tomorrow must be scheduled as
one batch; their PendingIntents intentionally share per-prayer identities.

Use **Run 30-second alarm test**, lock the screen, and listen. This uses the
real AlarmManager receiver and foreground playback service, raises the alarm
stream immediately to maximum, and stops after 20 seconds. A recorded audio
start is not proof of audible sound; **I heard the test** records explicit
confirmation. Check again after changing DND, battery, or audio routing settings.

Verify rescheduling after reboot, app update, time/time-zone changes, and exact
alarm access changes. Android does not run alarms while powered off or after a
user force-stops the app; reopen Omono after a force-stop. Prayer settings use
credential-protected storage, so unlock the phone once after restarting it. A phone's DND policy,
restricted profile, speaker routing, or manufacturer power controls can still
prevent audible playback; use the panel's settings links and the locked-screen
test on the actual phone rather than treating a scheduled alarm as a guarantee.
