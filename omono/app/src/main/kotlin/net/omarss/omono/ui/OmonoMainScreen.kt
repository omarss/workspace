package net.omarss.omono.ui

import android.Manifest
import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.MultiplePermissionsState
import com.google.accompanist.permissions.rememberMultiplePermissionsState
import net.omarss.omono.core.common.SpeedUnit
import net.omarss.omono.core.service.FeatureHostService

// Required at runtime to start the foreground location service.
// Background location is requested in a follow-up step (Android requires
// a separate prompt) — kept out of this list to avoid the system dialog
// burying the rationale for fine location.
private val foregroundPermissions: List<String> = buildList {
    add(Manifest.permission.ACCESS_FINE_LOCATION)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun OmonoMainScreen(
    contentPadding: PaddingValues,
    viewModel: OmonoMainViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val unit by viewModel.unit.collectAsState()
    val permissionsState = rememberMultiplePermissionsState(foregroundPermissions)

    @OptIn(ExperimentalPermissionsApi::class)
    val backgroundPermissionState = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        rememberMultiplePermissionsState(listOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION))
    } else {
        null
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .padding(horizontal = 24.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Text(
            text = "Omono",
            style = androidx.compose.material3.MaterialTheme.typography.headlineMedium,
        )

        PermissionsCard(
            foreground = permissionsState,
            background = backgroundPermissionState,
        )

        UnitPicker(
            current = unit,
            onSelect = viewModel::setUnit,
        )

        Spacer(Modifier.height(8.dp))

        Button(
            onClick = { FeatureHostService.start(context) },
            enabled = permissionsState.allPermissionsGranted,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Start tracking")
        }

        OutlinedButton(
            onClick = { FeatureHostService.stop(context) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Stop tracking")
        }
    }
}

@OptIn(ExperimentalPermissionsApi::class)
@Composable
private fun PermissionsCard(
    foreground: MultiplePermissionsState,
    background: MultiplePermissionsState?,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val foregroundOk = foreground.allPermissionsGranted
            val backgroundOk = background?.allPermissionsGranted ?: true

            Text(
                text = when {
                    foregroundOk && backgroundOk -> "All permissions granted"
                    foregroundOk -> "Background location not granted"
                    else -> "Location & notification permissions required"
                },
                style = androidx.compose.material3.MaterialTheme.typography.titleMedium,
            )
            Text(
                text = "Speed monitoring needs precise location while running, " +
                    "and background location to keep working when you leave the app.",
                style = androidx.compose.material3.MaterialTheme.typography.bodyMedium,
            )
            if (!foregroundOk) {
                Button(onClick = { foreground.launchMultiplePermissionRequest() }) {
                    Text("Grant location & notifications")
                }
            } else if (background != null && !backgroundOk) {
                Button(onClick = { background.launchMultiplePermissionRequest() }) {
                    Text("Grant background location")
                }
            }
        }
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
