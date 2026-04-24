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
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Mosque
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
import net.omarss.omono.ui.MoreRoute
import net.omarss.omono.ui.OmonoMainRoute
import net.omarss.omono.ui.compass.CompassRoute
import net.omarss.omono.ui.docs.DocsRoute
import net.omarss.omono.ui.finance.FinanceDashboardRoute
import net.omarss.omono.ui.places.PlacesRoute
import net.omarss.omono.ui.prayer.PrayerRoute
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
                        composable(Destination.Prayer.route) {
                            PrayerRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.Places.route) {
                            PlacesRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.More.route) {
                            MoreRoute(
                                contentPadding = PaddingValues(0.dp),
                                onOpen = { route -> navController.navigate(route) },
                            )
                        }
                        // Secondary destinations are reached via the
                        // More screen — not shown in the bottom bar.
                        composable(SecondaryDestination.Finance.route) {
                            FinanceDashboardRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(SecondaryDestination.Compass.route) {
                            CompassRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(SecondaryDestination.Quiz.route) {
                            QuizRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(SecondaryDestination.Docs.route) {
                            DocsRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(SecondaryDestination.Settings.route) {
                            SettingsRoute(contentPadding = PaddingValues(0.dp))
                        }
                    }
                }
            }
        }
    }
}

// Primary destinations — what lives in the bottom bar. Kept to 4
// per Material guidance so icons + labels don't crowd. "More" is
// the overflow entry to every Secondary destination.
enum class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector,
) {
    Tracking(route = "tracking", label = "Drive", icon = Icons.Filled.Speed),
    Prayer(route = "prayer", label = "Prayer", icon = Icons.Filled.Mosque),
    Places(route = "places", label = "Places", icon = Icons.Filled.LocationOn),
    More(route = "more", label = "More", icon = Icons.Filled.Apps),
}

// Secondary destinations — reachable from the More screen's grid.
// Not in the bottom bar. Settings lives here rather than in the
// primary nav because it's rarely opened during a drive.
enum class SecondaryDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
    val subtitle: String,
) {
    Finance(
        route = "finance",
        label = "Finance",
        icon = Icons.Filled.Payments,
        subtitle = "Today's spending, monthly budget, SMS totals.",
    ),
    Compass(
        route = "compass",
        label = "Compass",
        icon = Icons.Filled.Explore,
        subtitle = "Qibla bearing and nearest-mosque direction.",
    ),
    Quiz(
        route = "quiz",
        label = "Quiz",
        icon = Icons.Filled.Quiz,
        subtitle = "Multi-choice questions from the docs bundle.",
    ),
    Docs(
        route = "docs",
        label = "Docs",
        icon = Icons.AutoMirrored.Filled.MenuBook,
        subtitle = "Browse and listen to the docs corpus.",
    ),
    Settings(
        route = "settings",
        label = "Settings",
        icon = Icons.Filled.Settings,
        subtitle = "Units, alerts, voices, prayer method, budgets.",
    ),
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
            // "More" also counts as selected when the user is inside
            // one of the secondary destinations it links to — gives
            // a clear breadcrumb back.
            val secondaryRoutes = if (dest == Destination.More) {
                SecondaryDestination.entries.map { it.route }.toSet()
            } else emptySet()
            val selected = currentRoute?.hierarchy?.any {
                it.route == dest.route || it.route in secondaryRoutes
            } == true
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
