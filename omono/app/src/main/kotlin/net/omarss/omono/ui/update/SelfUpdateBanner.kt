package net.omarss.omono.ui.update

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.InstallMobile
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

// Self-update call-to-action surfaced at the top of the main screen.
// Three states (all composed from the same state object):
//   1. install permission missing  → "Allow installs" CTA
//   2. idle update available       → "Download" + dismiss
//   3. downloading                 → progress bar
//   4. download complete           → "Install now" CTA
@Composable
fun SelfUpdateBanner(
    state: SelfUpdateUiState,
    onDownload: () -> Unit,
    onInstall: () -> Unit,
    onGrantPermission: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val info = state.available ?: return

    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Update available",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                    Text(
                        text = "omono ${info.latest.version}",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
                IconButton(onClick = onDismiss) {
                    Icon(
                        imageVector = Icons.Filled.Close,
                        contentDescription = "Dismiss",
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }

            if (info.cumulativeChangelog.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    info.cumulativeChangelog.take(4).forEach { line ->
                        Text(
                            text = "• $line",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                    if (info.cumulativeChangelog.size > 4) {
                        Text(
                            text = "+ ${info.cumulativeChangelog.size - 4} more",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                }
            }

            Spacer(Modifier.height(2.dp))

            when {
                !state.canInstall -> {
                    Button(
                        onClick = onGrantPermission,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Allow installs from omono")
                    }
                    Text(
                        text = "Android needs your permission to install apps outside the Play Store.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }

                state.downloadedApk != null -> {
                    Button(
                        onClick = onInstall,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Filled.InstallMobile, contentDescription = null)
                        Spacer(Modifier.height(0.dp))
                        Text(
                            text = "  Install now",
                        )
                    }
                }

                state.isDownloading -> {
                    val percent = state.downloadPercent ?: 0
                    LinearProgressIndicator(
                        progress = { percent / 100f },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        text = "Downloading… $percent%",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }

                else -> {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Button(
                            onClick = onDownload,
                            modifier = Modifier.weight(1f),
                        ) {
                            Icon(Icons.Filled.Download, contentDescription = null)
                            Text(text = "  Download")
                        }
                        TextButton(onClick = onDismiss) {
                            Text("Later")
                        }
                    }
                }
            }

            state.error?.let { message ->
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}
