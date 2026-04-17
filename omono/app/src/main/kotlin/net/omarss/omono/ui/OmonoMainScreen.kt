package net.omarss.omono.ui

import android.Manifest
import android.content.Intent
import android.os.Build
import android.widget.Toast
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.core.content.FileProvider
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.DoNotDisturbOn
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.LocationOff
import androidx.compose.material.icons.automirrored.filled.Message
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.PieChart
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Route
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.ProgressIndicatorDefaults
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.rememberMultiplePermissionsState
import net.omarss.omono.BuildConfig
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureHostService
import net.omarss.omono.ui.update.SelfUpdateBanner
import net.omarss.omono.ui.update.SelfUpdateUiState
import net.omarss.omono.ui.update.SelfUpdateViewModel

private val foregroundPermissions: List<String> = buildList {
    add(Manifest.permission.ACCESS_FINE_LOCATION)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}

private val smsPermissions: List<String> = listOf(
    Manifest.permission.READ_SMS,
    Manifest.permission.RECEIVE_SMS,
)

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun OmonoMainRoute(
    contentPadding: PaddingValues,
    onOpenPlaces: () -> Unit = {},
    onOpenFinance: () -> Unit = {},
    viewModel: OmonoMainViewModel = hiltViewModel(),
    updateViewModel: SelfUpdateViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val updateState by updateViewModel.state.collectAsStateWithLifecycle()

    // Re-check "Install unknown sources" every time the user returns to
    // the main screen — they may have flipped the toggle while the app
    // was backgrounded by the system settings deep-link.
    LaunchedEffect(Unit) {
        updateViewModel.refreshPermission()
    }

    val foreground = rememberMultiplePermissionsState(foregroundPermissions)
    val background = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        rememberMultiplePermissionsState(listOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
    } else {
        null
    }
    val sms = rememberMultiplePermissionsState(smsPermissions)
    val batteryExempt by rememberBatteryOptimizationState()
    val dndAccessGranted by rememberNotificationPolicyAccessState()

    // Turn one-shot export events into FileProvider ACTION_SEND intents.
    LaunchedEffect(Unit) {
        viewModel.exportEvents.collect { event ->
            when (event) {
                is ExportEvent.Success -> launchSmsExportShare(context, event)
                is ExportEvent.Failure ->
                    Toast.makeText(context, "Export failed: ${event.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    OmonoMainScreen(
        contentPadding = contentPadding,
        state = state,
        updateState = updateState,
        foregroundGranted = foreground.allPermissionsGranted,
        backgroundGranted = background?.allPermissionsGranted ?: true,
        smsGranted = sms.allPermissionsGranted,
        batteryExempt = batteryExempt,
        dndAccessGranted = dndAccessGranted,
        onRequestForeground = foreground::launchMultiplePermissionRequest,
        onRequestBackground = { background?.launchMultiplePermissionRequest() },
        onRequestSms = sms::launchMultiplePermissionRequest,
        onRequestBatteryExemption = { launchBatteryOptimizationDialog(context) },
        onRequestDndAccess = { launchNotificationPolicyAccessSettings(context) },
        onUnitSelect = viewModel::setUnit,
        onAlertOnOverLimitChange = viewModel::setAlertOnOverLimit,
        onAlertOnTrafficAheadChange = viewModel::setAlertOnTrafficAhead,
        onAlertOnPhoneUseWhileDrivingChange = viewModel::setAlertOnPhoneUseWhileDriving,
        onBudgetChange = viewModel::setMonthlyBudget,
        onExportSms = viewModel::onExportSmsRequested,
        onOpenPlaces = onOpenPlaces,
        onOpenFinance = onOpenFinance,
        onDownloadUpdate = updateViewModel::startDownload,
        onInstallUpdate = updateViewModel::installNow,
        onGrantInstallPermission = updateViewModel::grantInstallPermission,
        onDismissUpdate = updateViewModel::dismiss,
        onStart = { FeatureHostService.start(context) },
        onStop = { FeatureHostService.stop(context) },
    )
}

private fun launchSmsExportShare(
    context: android.content.Context,
    event: ExportEvent.Success,
) {
    val uri = FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        event.file,
    )
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(
            Intent.EXTRA_SUBJECT,
            "Omono bank SMS export (${event.count} messages)",
        )
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    context.startActivity(Intent.createChooser(send, "Share SMS export").apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    })
}

@Composable
fun OmonoMainScreen(
    contentPadding: PaddingValues,
    state: OmonoMainUiState,
    updateState: SelfUpdateUiState = SelfUpdateUiState(),
    foregroundGranted: Boolean,
    backgroundGranted: Boolean,
    smsGranted: Boolean,
    batteryExempt: Boolean,
    dndAccessGranted: Boolean,
    onRequestForeground: () -> Unit,
    onRequestBackground: () -> Unit,
    onRequestSms: () -> Unit,
    onRequestBatteryExemption: () -> Unit,
    onRequestDndAccess: () -> Unit,
    onUnitSelect: (SpeedUnit) -> Unit,
    onAlertOnOverLimitChange: (Boolean) -> Unit,
    onAlertOnTrafficAheadChange: (Boolean) -> Unit,
    onAlertOnPhoneUseWhileDrivingChange: (Boolean) -> Unit,
    onBudgetChange: (Double) -> Unit,
    onExportSms: () -> Unit,
    onOpenPlaces: () -> Unit = {},
    onOpenFinance: () -> Unit = {},
    onDownloadUpdate: () -> Unit = {},
    onInstallUpdate: () -> Unit = {},
    onGrantInstallPermission: () -> Unit = {},
    onDismissUpdate: () -> Unit = {},
    onStart: () -> Unit,
    onStop: () -> Unit,
) {
    var showBudgetDialog by remember { mutableStateOf(false) }
    if (showBudgetDialog) {
        BudgetDialog(
            currentBudget = state.spending.budgetSar,
            onDismiss = { showBudgetDialog = false },
            onConfirm = { value ->
                onBudgetChange(value)
                showBudgetDialog = false
            },
        )
    }

    // Root Column scrolls because on smaller devices the stack of
    // permission / battery / DND / spending cards can easily exceed
    // the viewport height before any of them are dismissed.
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        BrandHeader(
            onOpenPlaces = onOpenPlaces,
            onOpenFinance = onOpenFinance,
        )

        AnimatedVisibility(visible = updateState.showBanner) {
            SelfUpdateBanner(
                state = updateState,
                onDownload = onDownloadUpdate,
                onInstall = onInstallUpdate,
                onGrantPermission = onGrantInstallPermission,
                onDismiss = onDismissUpdate,
            )
        }

        HeroCard(state = state)

        AnimatedVisibility(visible = state.spending.available || !smsGranted) {
            SpendingCard(
                spending = state.spending,
                smsGranted = smsGranted,
                onRequestSms = onRequestSms,
                onEditBudget = { showBudgetDialog = true },
                onExportSms = onExportSms,
            )
        }

        AnimatedVisibility(visible = state.recentTrips.isNotEmpty()) {
            RecentTripsCard(trips = state.recentTrips)
        }

        AnimatedVisibility(visible = !foregroundGranted || !backgroundGranted) {
            PermissionsCard(
                foregroundGranted = foregroundGranted,
                backgroundGranted = backgroundGranted,
                onRequestForeground = onRequestForeground,
                onRequestBackground = onRequestBackground,
            )
        }

        AnimatedVisibility(visible = !batteryExempt) {
            BatteryCard(onRequest = onRequestBatteryExemption)
        }

        AnimatedVisibility(visible = state.alertOnOverLimit && !dndAccessGranted) {
            DndAccessCard(onRequest = onRequestDndAccess)
        }

        Text(
            text = "Unit",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        UnitPicker(current = state.unit, onSelect = onUnitSelect)

        AlertSettingRow(
            enabled = state.alertOnOverLimit,
            onChange = onAlertOnOverLimitChange,
        )

        TrafficAlertSettingRow(
            enabled = state.alertOnTrafficAhead,
            onChange = onAlertOnTrafficAheadChange,
        )

        PhoneUseAlertSettingRow(
            enabled = state.alertOnPhoneUseWhileDriving,
            onChange = onAlertOnPhoneUseWhileDrivingChange,
        )

        Spacer(Modifier.height(4.dp))

        PrimaryAction(
            running = state.running,
            enabled = foregroundGranted,
            onStart = onStart,
            onStop = onStop,
        )
    }
}

@Composable
private fun BrandHeader(
    onOpenPlaces: () -> Unit,
    onOpenFinance: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "omono",
                style = MaterialTheme.typography.headlineLarge,
                color = MaterialTheme.colorScheme.primary,
            )
            // Version string is pulled from BuildConfig so every release
            // bump via `make release` is reflected here automatically.
            Text(
                text = "v${BuildConfig.VERSION_NAME}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        IconButton(onClick = onOpenFinance) {
            Icon(
                imageVector = Icons.Filled.PieChart,
                contentDescription = "Finance dashboard",
                tint = MaterialTheme.colorScheme.primary,
            )
        }
        IconButton(onClick = onOpenPlaces) {
            Icon(
                imageVector = Icons.Filled.Explore,
                contentDescription = "Places nearby",
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun HeroCard(state: OmonoMainUiState) {
    val overLimitColor = MaterialTheme.colorScheme.errorContainer
    val defaultColor = Color.White
    val heroColor by animateColorAsState(
        targetValue = if (state.overLimit) overLimitColor else defaultColor,
        label = "heroColor",
    )

    val gradientColors = listOf(
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.tertiary
    )

    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 8.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Brush.linearGradient(gradientColors))
                .padding(horizontal = 24.dp, vertical = 48.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            StatusDot(state)
            Spacer(Modifier.height(12.dp))
            Text(
                text = state.heroValue,
                style = MaterialTheme.typography.displayLarge,
                color = heroColor,
            )
            Text(
                text = state.heroUnit,
                style = MaterialTheme.typography.titleLarge,
                color = Color.White.copy(alpha = 0.8f),
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = state.status.label,
                style = MaterialTheme.typography.labelLarge,
                color = Color.White.copy(alpha = 0.9f),
            )
            if (state.limitDisplay != null) {
                Spacer(Modifier.height(12.dp))
                LimitChip(text = "Limit ${state.limitDisplay}", overLimit = state.overLimit)
            }
        }
    }
}

@Composable
private fun SpendingCard(
    spending: SpendingUi,
    smsGranted: Boolean,
    onRequestSms: () -> Unit,
    onEditBudget: () -> Unit,
    onExportSms: () -> Unit,
) {
    val walletGradient = listOf(
        MaterialTheme.colorScheme.secondaryContainer,
        MaterialTheme.colorScheme.surfaceVariant
    )

    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        shape = MaterialTheme.shapes.medium,
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 2.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Brush.linearGradient(walletGradient))
                .padding(horizontal = 24.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = "Digital Wallet",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (!smsGranted) {
                Text(
                    text = "Grant SMS access to read your Al Rajhi and STC " +
                        "Bank transaction messages. Nothing is uploaded — " +
                        "totals are computed on-device.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                FilledTonalButton(
                    onClick = onRequestSms,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.AutoMirrored.Filled.Message, contentDescription = null)
                    Spacer(Modifier.size(8.dp))
                    Text("Grant SMS access")
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    SpendingStat(label = "Today", value = "SAR ${spending.today}")
                    SpendingStat(label = "Month", value = "SAR ${spending.month}")
                }

                if (spending.transfersMonth != null) {
                    Text(
                        text = "Transfers this month: SAR ${spending.transfersMonth}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                if (spending.budgetSar > 0) {
                    Spacer(Modifier.height(4.dp))
                    val progressColor = if (spending.overBudget) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    }
                    LinearProgressIndicator(
                        progress = { spending.monthProgress },
                        modifier = Modifier.fillMaxWidth(),
                        color = progressColor,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant,
                    )
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "Budget SAR ${spending.budgetDisplay}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(onClick = onEditBudget) {
                            Icon(
                                Icons.Filled.Edit,
                                contentDescription = "Edit budget",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }

                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                TextButton(
                    onClick = onExportSms,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.Download, contentDescription = null)
                    Spacer(Modifier.size(8.dp))
                    Text("Share SMS for analysis")
                }
            }
        }
    }
}

@Composable
private fun RecentTripsCard(trips: List<TripUi>) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Filled.Route,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.size(8.dp))
                Text(
                    text = "Recent trips",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            trips.forEachIndexed { index, trip ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(
                        text = trip.startedAt,
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        Text(
                            text = trip.distance,
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = "max ${trip.maxSpeed}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = trip.duration,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
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
                        "The progress bar on the spending card turns red if you go over.",
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

@Composable
private fun SpendingStat(label: String, value: String) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
    }
}

@Composable
private fun StatusDot(state: OmonoMainUiState) {
    // The dot sits on a gradient background so we use high-contrast
    // colors that stay visible on both indigo and violet.
    val color by animateColorAsState(
        targetValue = when (state.status) {
            is Status.Tracking -> Color(0xFF4ADE80) // green-400
            is Status.Waiting -> Color.White.copy(alpha = 0.6f)
            is Status.Error -> MaterialTheme.colorScheme.error
            Status.Stopped -> Color.White.copy(alpha = 0.3f)
        },
        label = "statusDot",
    )
    Box(
        modifier = Modifier
            .size(12.dp)
            .clip(CircleShape)
            .background(color),
    )
}

@Composable
private fun LimitChip(text: String, overLimit: Boolean) {
    val container = if (overLimit) {
        MaterialTheme.colorScheme.errorContainer
    } else {
        MaterialTheme.colorScheme.secondaryContainer
    }
    val onContainer = if (overLimit) {
        MaterialTheme.colorScheme.onErrorContainer
    } else {
        MaterialTheme.colorScheme.onSecondaryContainer
    }
    Box(
        modifier = Modifier
            .clip(CircleShape)
            .background(container)
            .padding(horizontal = 14.dp, vertical = 6.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelLarge,
            color = onContainer,
        )
    }
}

@Composable
private fun UnitPicker(
    current: SpeedUnit,
    onSelect: (SpeedUnit) -> Unit,
) {
    val options = SpeedUnit.entries
    SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
        options.forEachIndexed { index, option ->
            SegmentedButton(
                selected = option == current,
                onClick = { onSelect(option) },
                shape = SegmentedButtonDefaults.itemShape(index = index, count = options.size),
            ) {
                Text(option.label)
            }
        }
    }
}

@Composable
private fun AlertSettingRow(
    enabled: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Alert over limit",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Loud beep the moment you cross a posted speed limit",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = enabled, onCheckedChange = onChange)
    }
}

@Composable
private fun TrafficAlertSettingRow(
    enabled: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Traffic ahead",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Heads-up tone when the road ~500 m ahead is jammed",
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
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "No phone while driving",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Continuous beep the whole time the screen is on once the app decides you're driving. " +
                    "Stops the moment you lock the phone.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = enabled, onCheckedChange = onChange)
    }
}

@Composable
private fun PermissionsCard(
    foregroundGranted: Boolean,
    backgroundGranted: Boolean,
    onRequestForeground: () -> Unit,
    onRequestBackground: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            val icon = if (foregroundGranted) Icons.Filled.NotificationsActive else Icons.Filled.LocationOff
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onTertiaryContainer,
            )
            Text(
                text = when {
                    !foregroundGranted -> "Location & notifications needed"
                    !backgroundGranted -> "Background location needed"
                    else -> "All permissions granted"
                },
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
            )
            Text(
                text = "Omono needs precise location while tracking, plus background " +
                    "location to keep measuring when you leave the app.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
            )
            when {
                !foregroundGranted -> FilledTonalButton(
                    onClick = onRequestForeground,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Grant location & notifications") }
                !backgroundGranted -> FilledTonalButton(
                    onClick = onRequestBackground,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Grant background location") }
            }
        }
    }
}

@Composable
private fun DndAccessCard(onRequest: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                imageVector = Icons.Filled.DoNotDisturbOn,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "Bypass Do Not Disturb",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "Grant Do Not Disturb access so the over-limit beep " +
                    "stays loud even when your phone is silenced. Android " +
                    "doesn't allow apps to bypass \"Total silence\" mode.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            FilledTonalButton(
                onClick = onRequest,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Open DND access settings") }
        }
    }
}

@Composable
private fun BatteryCard(onRequest: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                imageVector = Icons.Filled.BatteryFull,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "Disable battery optimisation",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            Text(
                text = "Android may stop background tracking after a few minutes if " +
                    "Omono isn't on the battery allow-list. One tap fixes it.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer,
            )
            FilledTonalButton(
                onClick = onRequest,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Allow background activity") }
        }
    }
}

@Composable
private fun PrimaryAction(
    running: Boolean,
    enabled: Boolean,
    onStart: () -> Unit,
    onStop: () -> Unit,
) {
    if (running) {
        FilledTonalButton(
            onClick = onStop,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.filledTonalButtonColors(
                containerColor = MaterialTheme.colorScheme.errorContainer,
                contentColor = MaterialTheme.colorScheme.onErrorContainer,
            ),
        ) {
            Icon(Icons.Filled.Stop, contentDescription = null)
            Spacer(Modifier.size(8.dp))
            Text("Stop tracking")
        }
    } else {
        Button(
            onClick = onStart,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null)
            Spacer(Modifier.size(8.dp))
            Text("Start tracking")
        }
    }
}
