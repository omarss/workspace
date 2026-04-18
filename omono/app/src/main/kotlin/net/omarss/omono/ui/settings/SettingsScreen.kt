package net.omarss.omono.ui.settings

import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.feature.speed.InternetGovernor
import net.omarss.omono.ui.ExportEvent
import net.omarss.omono.ui.launchSmsExportShare

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsRoute(
    contentPadding: PaddingValues,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var showBudgetDialog by remember { mutableStateOf(false) }

    // Permission state can change outside the app (user goes to
    // system Settings, toggles Usage access, comes back). Refresh on
    // every resume.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                viewModel.refreshUsageStatsPermission()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    // Surface export success/failure as toast + ACTION_SEND intent so
    // the user can immediately share the CSV.
    LaunchedEffect(Unit) {
        viewModel.exportEvents.collect { event ->
            when (event) {
                is ExportEvent.Success -> launchSmsExportShare(context, event)
                is ExportEvent.Failure ->
                    Toast.makeText(context, "Export failed: ${event.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    if (showBudgetDialog) {
        BudgetDialog(
            currentBudget = state.monthlyBudgetSar,
            onDismiss = { showBudgetDialog = false },
            onConfirm = {
                viewModel.setMonthlyBudget(it)
                showBudgetDialog = false
            },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(title = { Text("Settings") })

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            SectionCard(title = "Units") {
                UnitPicker(current = state.unit, onSelect = viewModel::setUnit)
            }

            SectionCard(title = "Alerts") {
                AlertSettingRow(
                    title = "Alert over limit",
                    subtitle = "Loud beep the moment you cross a posted speed limit.",
                    enabled = state.alertOnOverLimit,
                    onChange = viewModel::setAlertOnOverLimit,
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                PhoneUseAlertSettingRow(
                    enabled = state.alertOnPhoneUseWhileDriving,
                    usageStatsGranted = state.usageStatsGranted,
                    onChange = viewModel::setAlertOnPhoneUseWhileDriving,
                    onRequestUsageStats = { launchUsageStatsSettings(context) },
                )
            }

            SectionCard(title = "Internet kill-switch") {
                DisableInternetSettingRow(
                    enabled = state.disableInternetWhileDriving,
                    readiness = state.shizukuReadiness,
                    onChange = viewModel::setDisableInternetWhileDriving,
                    onRequestPermission = viewModel::requestShizukuPermission,
                )
            }

            SectionCard(title = "Spending") {
                SettingsActionRow(
                    title = "Monthly budget",
                    subtitle = "SAR %,.0f".format(state.monthlyBudgetSar),
                    onClick = { showBudgetDialog = true },
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                SettingsActionRow(
                    title = "Share SMS for analysis",
                    subtitle = "Exports bank SMSes to a file you can share.",
                    onClick = viewModel::onExportSmsRequested,
                )
            }

            Spacer(Modifier.height(8.dp))
        }
    }
}

// Container for a named settings group. Keeps each section visually
// separated so the screen scans as "rows in buckets" rather than one
// long list of switches.
@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.elevatedCardColors(
                containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
            ),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                content()
            }
        }
    }
}

@Composable
private fun UnitPicker(current: SpeedUnit, onSelect: (SpeedUnit) -> Unit) {
    val options = SpeedUnit.entries
    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        options.forEachIndexed { index, unit ->
            SegmentedButton(
                selected = current == unit,
                onClick = { onSelect(unit) },
                shape = SegmentedButtonDefaults.itemShape(index, options.size),
            ) { Text(unit.label) }
        }
    }
}

@Composable
private fun AlertSettingRow(
    title: String,
    subtitle: String,
    enabled: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = enabled, onCheckedChange = onChange)
    }
}

@Composable
private fun PhoneUseAlertSettingRow(
    enabled: Boolean,
    usageStatsGranted: Boolean,
    onChange: (Boolean) -> Unit,
    onRequestUsageStats: () -> Unit,
) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "No phone while driving",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "Loud beep once you've been using the phone for 5+ seconds while driving. " +
                        "Pauses automatically when Google Maps / Waze is foreground.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = enabled, onCheckedChange = onChange)
        }
        if (enabled && !usageStatsGranted) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = "Navigation-app detection needs Usage access — without it the beep fires " +
                    "whenever the screen is on (including when you're just using Maps).",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
            TextButton(onClick = onRequestUsageStats) {
                Text("Grant Usage access")
            }
        }
    }
}

@Composable
private fun DisableInternetSettingRow(
    enabled: Boolean,
    readiness: InternetGovernor.Readiness,
    onChange: (Boolean) -> Unit,
    onRequestPermission: () -> Unit,
) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Disable internet while driving",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "Wi-Fi + mobile data turn off when a drive starts and back on when it ends. " +
                        "Requires Shizuku for the elevation hop.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = enabled, onCheckedChange = onChange)
        }
        if (enabled && readiness != InternetGovernor.Readiness.Ready) {
            val message = when (readiness) {
                InternetGovernor.Readiness.NotInstalled ->
                    "Shizuku isn't installed. Install it from F-Droid or Play, then come back."
                InternetGovernor.Readiness.NotRunning ->
                    "Shizuku is installed but the service isn't running. Open Shizuku and start it via the ADB pair flow."
                InternetGovernor.Readiness.NoPermission ->
                    "Shizuku is running but omono hasn't been granted permission. Tap below to request."
                InternetGovernor.Readiness.Unknown ->
                    "Checking Shizuku status…"
                InternetGovernor.Readiness.Ready -> null
            }
            if (message != null) {
                Spacer(Modifier.height(6.dp))
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                if (readiness == InternetGovernor.Readiness.NoPermission) {
                    TextButton(onClick = onRequestPermission) {
                        Text("Grant Shizuku permission")
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsActionRow(
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun BudgetDialog(
    currentBudget: Double,
    onDismiss: () -> Unit,
    onConfirm: (Double) -> Unit,
) {
    var text by remember { mutableStateOf("%.0f".format(currentBudget)) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Monthly budget") },
        text = {
            Column {
                Text(
                    "Set the SAR amount you want to stay under each month. " +
                        "The monthly bar on Finance turns red when you cross it.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { new -> text = new.filter { it.isDigit() || it == '.' } },
                    label = { Text("SAR") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(text.toDoubleOrNull() ?: 0.0) }) {
                Text("Save")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

// Deep link into Settings → Apps → Special access → Usage access —
// Android doesn't expose an in-app grant path for PACKAGE_USAGE_STATS.
private fun launchUsageStatsSettings(context: Context) {
    val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(intent) }
}
