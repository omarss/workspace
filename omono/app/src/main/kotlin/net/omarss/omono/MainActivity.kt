package net.omarss.omono

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Scaffold
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.designsystem.theme.OmonoTheme
import net.omarss.omono.ui.OmonoMainRoute
import net.omarss.omono.ui.finance.FinanceDashboardRoute
import net.omarss.omono.ui.places.PlacesRoute

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            OmonoTheme {
                val navController = rememberNavController()
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    NavHost(
                        navController = navController,
                        startDestination = "main",
                    ) {
                        composable("main") {
                            OmonoMainRoute(
                                contentPadding = padding,
                                onOpenPlaces = { navController.navigate("places") },
                                onOpenFinance = { navController.navigate("finance") },
                            )
                        }
                        composable("places") {
                            PlacesRoute(
                                contentPadding = padding,
                                onBack = { navController.popBackStack() },
                            )
                        }
                        composable("finance") {
                            FinanceDashboardRoute(
                                contentPadding = padding,
                                onBack = { navController.popBackStack() },
                            )
                        }
                    }
                }
            }
        }
    }
}
