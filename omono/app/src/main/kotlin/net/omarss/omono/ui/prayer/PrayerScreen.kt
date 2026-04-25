package net.omarss.omono.ui.prayer

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Mosque
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Switch
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.prayer.AthanItem
import net.omarss.omono.feature.prayer.AthanSelection
import net.omarss.omono.feature.prayer.PrayerCalculationMethod
import net.omarss.omono.feature.prayer.PrayerKind
import net.omarss.omono.feature.prayer.PrayerTime
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrayerRoute(
    contentPadding: PaddingValues,
    viewModel: PrayerViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    // Document-picker contract. "audio/*" mime filter so the system
    // picker only surfaces audio files. We take a persistable URI
    // grant because we copy bytes into the app's own storage — the
    // grant isn't strictly necessary post-copy, but requesting it
    // doesn't hurt and handles OEM pickers that delay delivery.
    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) viewModel.importAthanFromUri(uri)
    }

    // Returning from the system battery-optimisation deep-link
    // doesn't fire onActivityResult — it's an open-ended Settings
    // page. Re-check the status on every ON_RESUME so the chip
    // updates the moment the user grants the exemption.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) viewModel.refreshBatteryOptStatus()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text("Prayer times") },
            actions = {
                IconButton(onClick = viewModel::refresh) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh from current location")
                }
            },
        )

        val today = state.today
        if (today == null) {
            WaitingForFix(state.permissionDenied)
            return@Column
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            LocationAndMethodRow(state)
            NextPrayerCard(state)
            PrayerList(state)
            ReliabilityCard(
                state = state,
                onToggle = viewModel::setReliabilityMode,
                onLaunchBatteryOptSettings = viewModel::launchBatteryOptSettings,
            )
            HardWakeCard(
                enabled = state.requireChallengeToStop,
                onToggle = viewModel::setRequireChallengeToStop,
            )
            AthanPickerCard(
                state = state,
                onPreview = viewModel::playAthanPreview,
                onStop = viewModel::stopAthanPreview,
                onSelect = viewModel::selectAthan,
                onDelete = viewModel::deleteAthan,
                onAddFile = { importLauncher.launch(arrayOf("audio/*")) },
            )
        }
    }
}

// Location chip + Umm al-Qura badge at the top of the Prayer tab.
// Answers "where am I computing from?" and "which method?" in one
// glance — both questions the user explicitly asked to have visible
// on this screen at all times.
@Composable
private fun LocationAndMethodRow(state: PrayerUiState) {
    val fix = state.lastFix
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AssistChip(
            onClick = {},
            label = {
                Text(
                    text = when {
                        state.locationLabel != null -> state.locationLabel!!
                        fix != null -> "%.4f, %.4f".format(fix.first, fix.second)
                        else -> "Locating…"
                    },
                )
            },
            leadingIcon = {
                Icon(
                    imageVector = Icons.Filled.LocationOn,
                    contentDescription = null,
                    modifier = Modifier.width(18.dp),
                )
            },
            colors = AssistChipDefaults.assistChipColors(),
        )
        AssistChip(
            onClick = {},
            label = { Text(state.method.display) },
            colors = AssistChipDefaults.assistChipColors(),
        )
    }
}

@Composable
private fun WaitingForFix(permissionDenied: Boolean) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            imageVector = Icons.Filled.Mosque,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = if (permissionDenied) "Location permission needed" else "Waiting for GPS",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = if (permissionDenied) {
                "Prayer times are computed locally from your GPS fix. " +
                    "Grant location access from the main screen to enable them."
            } else {
                "Once the device gets a fresh fix, today's times will show here. " +
                    "Works entirely offline after the first fix."
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun NextPrayerCard(state: PrayerUiState) {
    val next = state.nextPrayer ?: return
    val minutesUntil = ((next.atEpochMs - state.now) / 60_000L).coerceAtLeast(0L)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
        ) {
            Text(
                text = "Up next",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = next.kind.display,
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "${formatClock(next.atEpochMs)} · in ${formatMinutes(minutesUntil)}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
    }
}

@Composable
private fun PrayerList(state: PrayerUiState) {
    val today = state.today ?: return
    val nextAt = state.nextPrayer?.atEpochMs
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
    ) {
        Column(modifier = Modifier.padding(vertical = 4.dp)) {
            today.times.forEachIndexed { index, t ->
                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                PrayerRow(t, highlighted = t.atEpochMs == nextAt)
            }
        }
    }
}

@Composable
private fun PrayerRow(time: PrayerTime, highlighted: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (highlighted) {
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .height(24.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(MaterialTheme.colorScheme.primary),
            )
            Spacer(Modifier.width(10.dp))
        }
        Text(
            text = time.kind.display,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = if (highlighted) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
        )
        Text(
            text = formatClock(time.atEpochMs),
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// Fajr athan picker. Lists whatever recordings the user has imported
// plus a "Random" virtual row at the top. Radio-style single-select
// persists the choice so the alarm receiver plays the same file at
// the next Fajr. An "Add audio file" button opens the system SAF
// picker so the user can source from any app (Files / Drive / local
// media / downloads).
// Reliability card: surface the two levers that fix "athan didn't
// fire" in practice — battery-optimisation exemption (most often
// the actual culprit) and the optional always-on foreground service
// for OEMs that kill background processes regardless of doze.
@Composable
private fun ReliabilityCard(
    state: PrayerUiState,
    onToggle: (Boolean) -> Unit,
    onLaunchBatteryOptSettings: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "Reliability",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )

            // Reliability-mode toggle. Foreground service holds the
            // process resident across overnight idle — the belt-and-
            // braces fix for OEM aggressive kills.
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Reliability mode",
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = "Keeps a low-priority background notification " +
                            "so Fajr fires even if the OS would otherwise kill " +
                            "the app overnight. Costs one notification slot.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(checked = state.reliabilityMode, onCheckedChange = onToggle)
            }

            // Battery-optimisation status. When the app is *not*
            // exempted, surface a CTA — this is the single most
            // common cause of an alarm not firing on schedule.
            if (!state.ignoringBatteryOptimisations) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(onClick = onLaunchBatteryOptSettings)
                        .padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.Filled.WarningAmber,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.error,
                    )
                    Spacer(Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = "Battery optimisation is active",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Text(
                            text = "Tap to whitelist omono. Without this, Doze can " +
                                "delay or silence Fajr entirely.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            } else {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Filled.Bolt,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = "Battery optimisation exempt — alarms fire on schedule.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

// Anti-snooze gate toggle. When on, the Fajr athan cannot be
// dismissed without answering 3 multiple-choice questions (SAT,
// Qiyas, or advanced math) correctly in a row. The gate launches
// as a full-screen activity over the lock screen.
@Composable
private fun HardWakeCard(
    enabled: Boolean,
    onToggle: (Boolean) -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Hard wake",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = "You can't silence the Fajr athan without answering " +
                        "3 questions (SAT / Qiyas / math) in a row. Impossible " +
                        "to sleep through.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = enabled, onCheckedChange = onToggle)
        }
    }
}

@Composable
private fun AthanPickerCard(
    state: PrayerUiState,
    onPreview: () -> Unit,
    onStop: () -> Unit,
    onSelect: (AthanSelection) -> Unit,
    onDelete: (AthanItem) -> Unit,
    onAddFile: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "Fajr athan",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "Played only at Fajr — never at any other prayer. " +
                    "Volume fades in over 15 seconds from soft to loud. Pick " +
                    "one to play every day, or leave on Random to rotate. Add " +
                    "your favourite recordings with the ➕ button — they're " +
                    "copied into omono's own storage so the Fajr alarm works " +
                    "offline.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            val randomSelected = state.athanSelection is AthanSelection.Random
            AthanRow(
                selected = randomSelected,
                primary = "Random",
                secondary = when {
                    state.availableAthans.isEmpty() -> "No recordings yet — uses the default alarm sound at Fajr."
                    state.availableAthans.size == 1 -> "1 recording available."
                    else -> "${state.availableAthans.size} recordings in rotation."
                },
                icon = { Icon(Icons.Filled.Shuffle, contentDescription = null) },
                onClick = { onSelect(AthanSelection.Random) },
            )

            if (state.availableAthans.isNotEmpty()) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                state.availableAthans.forEach { item ->
                    val pinned = state.athanSelection is AthanSelection.Specific &&
                        (state.athanSelection as AthanSelection.Specific).fileName == item.identifier
                    val (secondary, trailing) = when (item) {
                        is AthanItem.Bundled ->
                            (item.credit ?: "Bundled") to null
                        is AthanItem.Local -> humanReadableSize(item.file.length()) to @Composable {
                            IconButton(onClick = { onDelete(item) }) {
                                Icon(
                                    imageVector = Icons.Filled.Delete,
                                    contentDescription = "Delete ${item.displayName}",
                                )
                            }
                        }
                    }
                    AthanRow(
                        selected = pinned,
                        primary = item.displayName,
                        secondary = secondary,
                        icon = null,
                        onClick = { onSelect(AthanSelection.Specific(item.identifier)) },
                        trailing = trailing,
                    )
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                FilledIconButton(onClick = onAddFile) {
                    Icon(Icons.Filled.Add, contentDescription = "Add audio file")
                }
                OutlinedButton(onClick = onPreview) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Preview")
                }
                OutlinedButton(onClick = onStop) {
                    Icon(Icons.Filled.Stop, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text("Stop")
                }
            }
        }
    }
}

@Composable
private fun AthanRow(
    selected: Boolean,
    primary: String,
    secondary: String?,
    icon: (@Composable () -> Unit)?,
    onClick: () -> Unit,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = onClick)
        if (icon != null) {
            icon()
            Spacer(Modifier.width(6.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = primary,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            )
            if (secondary != null) {
                Text(
                    text = secondary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        trailing?.invoke()
    }
}

private fun humanReadableSize(bytes: Long): String {
    val kb = bytes / 1024.0
    return when {
        bytes < 1024L -> "$bytes B"
        kb < 1024.0 -> "%.0f kB".format(kb)
        else -> "%.1f MB".format(kb / 1024.0)
    }
}

private val clockFormatter: DateTimeFormatter by lazy {
    DateTimeFormatter.ofPattern("HH:mm", Locale.getDefault())
        .withZone(ZoneId.systemDefault())
}

private fun formatClock(epochMs: Long): String =
    clockFormatter.format(Instant.ofEpochMilli(epochMs))

private fun formatMinutes(minutes: Long): String = when {
    minutes < 1L -> "less than a minute"
    minutes < 60L -> "$minutes min"
    else -> {
        val h = minutes / 60
        val m = minutes % 60
        if (m == 0L) "${h}h" else "${h}h ${m}m"
    }
}

private val PrayerKind.display: String
    get() = when (this) {
        PrayerKind.Fajr -> "Fajr"
        PrayerKind.Sunrise -> "Sunrise"
        PrayerKind.Dhuhr -> "Dhuhr"
        PrayerKind.Asr -> "Asr"
        PrayerKind.Maghrib -> "Maghrib"
        PrayerKind.Isha -> "Isha"
    }
