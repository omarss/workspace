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
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import net.omarss.omono.ui.twitter.TwitterBlue
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
import net.omarss.omono.ui.twitter.TwitterRoute

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
                        composable(Destination.Twitter.route) {
                            TwitterRoute(contentPadding = PaddingValues(0.dp))
                        }
                        composable(Destination.More.route) {
                            MoreRoute(
                                contentPadding = PaddingValues(0.dp),
                                onOpen = { route -> navController.navigate(route) },
                            )
                        }
                        // Secondary destinations are reached via the
                        // More screen — not shown in the bottom bar.
                        composable(SecondaryDestination.Prayer.route) {
                            PrayerRoute(contentPadding = PaddingValues(0.dp))
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
//
// Finance was previously a Secondary destination; it earns a primary
// slot because the spending dashboard is the most data-dense surface
// in the app and gets glanced at multiple times per day. Prayer moved
// down to More — still one tap from the home screen, but no longer
// competing with Finance for prime real estate.
enum class Destination(
    val route: String,
    val label: String,
    val icon: ImageVector?,
    // Optional drawable-resource icon for destinations that ship a
    // custom vector outside Material Icons. Mutually exclusive with
    // `icon` — call sites pick whichever is non-null.
    val iconRes: Int? = null,
) {
    Tracking(route = "tracking", label = "Drive", icon = Icons.Filled.Speed),
    Finance(route = "finance", label = "Finance", icon = Icons.Filled.Payments),
    Places(route = "places", label = "Places", icon = Icons.Filled.LocationOn),
    // Bird-silhouette icon + Twitter-blue tint (applied at the call site)
    // make this tab read as the classic Twitter app. The vector is a
    // stylized hand-drawn shape, not the trademarked logo.
    Twitter(route = "twitter", label = "Feed", icon = null, iconRes = R.drawable.ic_feed_bird),
    More(route = "more", label = "More", icon = Icons.Filled.Apps),
}

// Secondary destinations — reachable from the More screen's grid.
// Not in the bottom bar. Settings lives here because it's rarely
// opened during a drive; Prayer lives here because it's a daily
// utility, not an at-a-glance metric.
enum class SecondaryDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
    val subtitle: String,
) {
    Prayer(
        route = "prayer",
        label = "Prayer",
        icon = Icons.Filled.Mosque,
        subtitle = "Times, athan, next-prayer countdown.",
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

// Bottom-nav pattern: single-top per tab, pop back to the graph's
// start when leaving a tab, restore the tab's own back-stack state
// when the user returns to it.
//
// "More" is special: tapping it always opens the More screen, even
// if the user is currently inside a secondary destination (Finance /
// Compass / Quiz / Docs / Settings). The previous build short-
// circuited that tap because "More" was considered selected while
// inside its children — which left the user unable to jump between
// secondaries without a Back press first. The fix is to treat a
// secondary-page "More" tap as a navigation *to* More, not a no-op.
@Composable
private fun OmonoBottomNav(navController: NavHostController) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination
    NavigationBar {
        Destination.entries.forEach { dest ->
            val inSecondary = dest == Destination.More &&
                currentRoute?.hierarchy?.any { it.route in SECONDARY_ROUTES } == true
            val onRoute = currentRoute?.hierarchy?.any { it.route == dest.route } == true
            // Visual selection still lights up More while in a
            // secondary — that breadcrumb is helpful — but onClick
            // below navigates anyway instead of short-circuiting.
            val selected = onRoute || inSecondary
            // The Twitter tab gets the classic-Twitter blue selected tint;
            // every other tab inherits the global Material defaults. Pull
            // colors out conditionally rather than branching on the call
            // path so each tab keeps a single composable.
            val itemColors = if (dest == Destination.Twitter) {
                NavigationBarItemDefaults.colors(
                    selectedIconColor = TwitterBlue,
                    selectedTextColor = TwitterBlue,
                    indicatorColor = TwitterBlue.copy(alpha = 0.15f),
                )
            } else {
                NavigationBarItemDefaults.colors()
            }
            NavigationBarItem(
                selected = selected,
                colors = itemColors,
                onClick = {
                    val sameTopLevel = onRoute
                    if (!sameTopLevel) {
                        navController.navigate(dest.route) {
                            popUpTo(navController.graph.findStartDestination().id) {
                                saveState = true
                            }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                },
                icon = {
                    when {
                        dest.iconRes != null -> Icon(
                            painter = painterResource(dest.iconRes),
                            contentDescription = dest.label,
                        )
                        dest.icon != null -> Icon(
                            imageVector = dest.icon,
                            contentDescription = dest.label,
                        )
                    }
                },
                label = { Text(dest.label) },
            )
        }
    }
}

private val SECONDARY_ROUTES: Set<String> =
    SecondaryDestination.entries.map { it.route }.toSet()
