package net.omarss.omono.ui

import android.Manifest
import android.os.Build
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BatteryFull
import androidx.compose.material.icons.filled.LocationOff
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.MultiplePermissionsState
import com.google.accompanist.permissions.rememberMultiplePermissionsState
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureHostService

private val foregroundPermissions: List<String> = buildList {
    add(Manifest.permission.ACCESS_FINE_LOCATION)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun OmonoMainRoute(
    contentPadding: PaddingValues,
    viewModel: OmonoMainViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    val foreground = rememberMultiplePermissionsState(foregroundPermissions)
    val background = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        rememberMultiplePermissionsState(listOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
    } else {
        null
    }
    val batteryExempt by rememberBatteryOptimizationState()

    OmonoMainScreen(
        contentPadding = contentPadding,
        state = state,
        foregroundGranted = foreground.allPermissionsGranted,
        backgroundGranted = background?.allPermissionsGranted ?: true,
        batteryExempt = batteryExempt,
        onRequestForeground = foreground::launchMultiplePermissionRequest,
        onRequestBackground = { background?.launchMultiplePermissionRequest() },
        onRequestBatteryExemption = { launchBatteryOptimizationDialog(context) },
        onUnitSelect = viewModel::setUnit,
        onAlertOnOverLimitChange = viewModel::setAlertOnOverLimit,
        onStart = { FeatureHostService.start(context) },
        onStop = { FeatureHostService.stop(context) },
    )
}

@Composable
fun OmonoMainScreen(
    contentPadding: PaddingValues,
    state: OmonoMainUiState,
    foregroundGranted: Boolean,
    backgroundGranted: Boolean,
    batteryExempt: Boolean,
    onRequestForeground: () -> Unit,
    onRequestBackground: () -> Unit,
    onRequestBatteryExemption: () -> Unit,
    onUnitSelect: (SpeedUnit) -> Unit,
    onAlertOnOverLimitChange: (Boolean) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .padding(horizontal = 24.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        BrandHeader()
        HeroCard(state = state)

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
private fun BrandHeader() {
    Text(
        text = "omono",
        style = MaterialTheme.typography.headlineLarge,
        color = MaterialTheme.colorScheme.primary,
    )
}

@Composable
private fun HeroCard(state: OmonoMainUiState) {
    val heroColor by animateColorAsState(
        targetValue = if (state.overLimit) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.onSurface
        },
        label = "heroColor",
    )

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 32.dp),
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
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = state.status.label,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (state.limitDisplay != null) {
                Spacer(Modifier.height(12.dp))
                LimitChip(text = "Limit ${state.limitDisplay}", overLimit = state.overLimit)
            }
        }
    }
}

@Composable
private fun StatusDot(state: OmonoMainUiState) {
    val color by animateColorAsState(
        targetValue = when (state.status) {
            is Status.Tracking -> MaterialTheme.colorScheme.primary
            is Status.Waiting -> MaterialTheme.colorScheme.tertiary
            is Status.Error -> MaterialTheme.colorScheme.error
            Status.Stopped -> MaterialTheme.colorScheme.outlineVariant
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
    androidx.compose.foundation.layout.Row(
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
private fun PermissionsCard(
    foregroundGranted: Boolean,
    backgroundGranted: Boolean,
    onRequestForeground: () -> Unit,
    onRequestBackground: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
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
private fun BatteryCard(onRequest: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
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
