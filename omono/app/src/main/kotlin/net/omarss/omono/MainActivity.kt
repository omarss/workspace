package net.omarss.omono

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Scaffold
import androidx.compose.ui.Modifier
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.designsystem.theme.OmonoTheme
import net.omarss.omono.ui.OmonoMainScreen

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            OmonoTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    OmonoMainScreen(contentPadding = padding)
                }
            }
        }
    }
}
