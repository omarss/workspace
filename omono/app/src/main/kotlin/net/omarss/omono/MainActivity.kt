package net.omarss.omono

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Quiz
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import dagger.hilt.android.AndroidEntryPoint
import net.omarss.omono.core.designsystem.theme.OmonoTheme
import net.omarss.omono.settings.AppSettingsViewModel
import net.omarss.omono.settings.ThemePreference
import net.omarss.omono.ui.OmonoMainRoute
import net.omarss.omono.ui.compass.CompassRoute
import net.omarss.omono.ui.finance.FinanceDashboardRoute
import net.omarss.omono.ui.places.PlacesRoute
import net.omarss.omono.ui.quiz.QuizRoute
import net.omarss.omono.ui.settings.SettingsRoute

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val appSettingsViewModel: AppSettingsViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val preference by appSettingsViewModel.theme.collectAsStateWithLifecycle()
            val darkTheme = when (preference) {
                ThemePreference.Auto -> isSystemInDarkTheme()
                ThemePreference.Light -> false
                ThemePreference.Dark -> true
            }
            OmonoTheme(darkTheme = darkTheme) {
                val navController = rememberNavController()
                Scaffold(
                    modifier = Modifier.fillMaxSize(),
                    bottomBar = { OmonoBottomNav(navController = navController) },
                ) { innerPadding ->
                    NavHost(
                        navController = navController,
                        startDestination = Destination.Tracking.route,
                        modifier = Modifier.padding(innerPadding),
                    ) {
                        composable(Destination.Tracking.route) {
                            OmonoMainRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Finance.route) {
                            FinanceDashboardRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Places.route) {
                            PlacesRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Compass.route) {
                            CompassRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Quiz.route) {
                            QuizRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Settings.route) {
                            SettingsRoute(contentPadding = PaddingValues(0.dp))
                        }
                    }
                }
            }
        }
    }
}

// Every top-level tab in one enum. Adding a new tab = new enum
// entry + matching composable() in the NavHost above.
private enum class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Tracking(route = "tracking", label = "Drive", icon = Icons.Filled.Speed),
    Finance(route = "finance", label = "Finance", icon = Icons.Filled.Payments),
    Places(route = "places", label = "Places", icon = Icons.Filled.LocationOn),
    Compass(route = "compass", label = "Compass", icon = Icons.Filled.Explore),
    Quiz(route = "quiz", label = "Quiz", icon = Icons.Filled.Quiz),
    Settings(route = "settings", label = "Settings", icon = Icons.Filled.Settings),
}

// Standard bottom-nav pattern: single-top per tab, pop back to the
// graph's start when leaving a tab, restore the tab's own back-stack
// state when the user returns to it.
@Composable
private fun OmonoBottomNav(navController: NavHostController) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination
    NavigationBar {
        Destination.entries.forEach { dest ->
            val selected = currentRoute?.hierarchy?.any { it.route == dest.route } == true
            NavigationBarItem(
                selected = selected,
                onClick = {
                    if (!selected) {
                        navController.navigate(dest.route) {
                            popUpTo(navController.graph.findStartDestination().id) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                },
                icon = { Icon(dest.icon, contentDescription = dest.label) },
                label = { Text(dest.label) },
            )
        }
    }
}
