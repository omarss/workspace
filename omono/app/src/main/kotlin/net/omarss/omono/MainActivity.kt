package net.omarss.omono

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.designsystem.theme.OmonoTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            OmonoTheme {
                OmonoAppRoot()
            }
        }
    }
}

@Composable
private fun OmonoAppRoot() {
    Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
        Text(
            text = "Omono — scaffold ready",
            modifier = Modifier.padding(padding),
        )
    }
}
