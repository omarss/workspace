package net.omarss.omono.ui.places

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.expandVertically
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.FilterAltOff
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import net.omarss.omono.feature.places.Place
import net.omarss.omono.feature.places.PlaceCategory
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun PlacesRoute(
    contentPadding: PaddingValues,
    viewModel: PlacesViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val listState = rememberLazyListState()
    var showCustomizeDialog by remember { mutableStateOf(false) }

    if (showCustomizeDialog) {
        CustomizeCategoriesSheet(
            hidden = state.hiddenCategories,
            ordered = state.orderedCategories,
            onVisibilityChange = { category, visible ->
                // `visible = true` means the user wants the category
                // shown, i.e. NOT hidden → pass `hidden = !visible`.
                viewModel.setCategoryHidden(category, !visible)
            },
            onReorder = { from, to -> viewModel.reorderCategory(from, to) },
            onSetAllHidden = { isHidden -> viewModel.setAllCategoriesHidden(isHidden) },
            onReset = { viewModel.resetCategoryPreferences() },
            onDismiss = { showCustomizeDialog = false },
        )
    }

    // First-load: fire a refresh once the screen mounts. The user can
    // re-trigger via the refresh icon or by changing category/radius.
    LaunchedEffect(Unit) { viewModel.refresh() }

    // Collapse the filter stack while the user scrolls down through
    // the list and bring it back on scroll-up (or when they're
    // already near the top). Bare-bones direction detection is enough
    // — tracking actual pixel deltas across every list layout change
    // would be overkill for a UX tweak.
    var filtersExpanded by remember { mutableStateOf(true) }
    LaunchedEffect(listState) {
        var prevIndex = listState.firstVisibleItemIndex
        var prevOffset = listState.firstVisibleItemScrollOffset
        snapshotFlow {
            listState.firstVisibleItemIndex to listState.firstVisibleItemScrollOffset
        }.collect { (index, offset) ->
            val atTop = index == 0 && offset < TOP_EXPAND_THRESHOLD_PX
            val scrolledDown = index > prevIndex ||
                (index == prevIndex && offset > prevOffset + SCROLL_HYSTERESIS_PX)
            val scrolledUp = index < prevIndex ||
                (index == prevIndex && offset < prevOffset - SCROLL_HYSTERESIS_PX)
            when {
                atTop -> filtersExpanded = true
                scrolledDown -> filtersExpanded = false
                scrolledUp -> filtersExpanded = true
            }
            prevIndex = index
            prevOffset = offset
        }
    }

    // Jump back to the top of the list whenever the selected category
    // (or the cuisine sub-filter) changes — users expect a fresh result
    // set to start at the top, not continue from wherever they were
    // scrolled in the previous category.
    LaunchedEffect(state.category) {
        if (listState.firstVisibleItemIndex > 0) listState.scrollToItem(0)
        filtersExpanded = true
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
    ) {
        TopAppBar(
            title = { Text("Places nearby") },
            actions = {
                // Clear-all icon only lights up when any filter is
                // actually non-default — otherwise it'd visually
                // clutter the bar on a fresh-open screen for no action.
                if (hasActiveFilters(state)) {
                    IconButton(onClick = {
                        viewModel.clearFilters()
                    }) {
                        Icon(
                            Icons.Filled.FilterAltOff,
                            contentDescription = "Clear all filters",
                        )
                    }
                }
                IconButton(onClick = { showCustomizeDialog = true }) {
                    Icon(
                        Icons.Filled.Tune,
                        contentDescription = "Customize categories",
                    )
                }
                IconButton(onClick = { viewModel.refresh(force = true) }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                }
            },
        )

        AnimatedVisibility(
            visible = filtersExpanded,
            enter = expandVertically() + fadeIn(),
            exit = shrinkVertically() + fadeOut(),
        ) {
            Column(modifier = Modifier.fillMaxWidth()) {
                SearchField(
                    query = state.searchQuery,
                    onChange = viewModel::setSearchQuery,
                )

                CategoryChips(
                    selected = state.category,
                    hidden = state.hiddenCategories,
                    ordered = state.orderedCategories,
                    onSelect = viewModel::selectCategory,
                    modifier = Modifier.fillMaxWidth(),
                )

                // Cuisine sub-row only appears when the parent
                // category is a food bucket. Keeps the default view
                // clean; revealing specialty cuisines only where they
                // make sense.
                if (state.category in FOOD_PARENT_CATEGORIES) {
                    CuisineChips(
                        selected = state.category,
                        hidden = state.hiddenCategories,
                        ordered = state.orderedCategories,
                        onSelect = viewModel::selectCategory,
                    )
                }

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    ConePicker(
                        cone = state.coneDegrees,
                        onChange = viewModel::setCone,
                        modifier = Modifier.weight(1f),
                    )
                    RadiusPicker(
                        radiusMeters = state.radiusMeters,
                        onChange = viewModel::setRadius,
                        modifier = Modifier.weight(1f),
                    )
                }

                QualityFilterRow(
                    enabled = state.qualityFilter,
                    onChange = viewModel::setQualityFilter,
                )
            }
        }

        if (!state.configured) {
            EmptyState(
                title = "Places backend not configured",
                body = "Add gplaces.api.url and gplaces.api.key to local.properties " +
                    "and rebuild to enable the places search.",
            )
            return@Column
        }

        // No Crossfade — the animated swap between LoadingState and
        // PlaceList reads as flicker when the backend returns in
        // <200 ms. Straight if/else, renders instantly in whatever
        // state we're in. A thin top bar signals "still fetching"
        // without hiding existing results.
        if (state.loading && state.places.isEmpty()) {
            LoadingState()
            return@Column
        }
        if (state.errorMessage != null && state.places.isEmpty()) {
            EmptyState(
                title = "Couldn't load places",
                body = state.errorMessage.orEmpty(),
            )
            return@Column
        }
        if (state.places.isEmpty()) {
            EmptyState(
                title = "Nothing in that direction",
                body = "Widen the cone or pick a different category.",
            )
            return@Column
        }

        if (state.loading) {
            LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
            )
        }
        PlaceList(
            listState = listState,
            places = state.places,
            heading = state.heading,
            loadingMore = state.loadingMore,
            canLoadMore = state.canLoadMore,
            onOpenMap = { place -> launchMapsFor(context, place) },
            onCall = { phone -> launchDialer(context, phone) },
            onLoadMore = viewModel::loadMore,
        )
    }
}

// Bottom-sheet customise surface. Single scrollable list of every
// category, with a drag-handle on the left for free-form reorder
// (via sh.calvin.reorderable), tint-icon in a badge, tap-to-toggle
// label, and a visibility Switch. Cuisines carry a small "Cuisine"
// subtitle so the user can tell them apart from top-level picks
// without splitting the list into sections (which would make the
// reorder story awkward).
//
// Header actions — Show all / Hide all / Reset — plus a live
// "N of M showing" count.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CustomizeCategoriesSheet(
    hidden: Set<PlaceCategory>,
    ordered: List<PlaceCategory>,
    onVisibilityChange: (PlaceCategory, visible: Boolean) -> Unit,
    onReorder: (from: PlaceCategory, to: PlaceCategory) -> Unit,
    onSetAllHidden: (Boolean) -> Unit,
    onReset: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        val visibleCount = ordered.count { it !in hidden }
        val listState = rememberLazyListState()
        val reorderState = rememberReorderableLazyListState(listState) { from, to ->
            // from.key / to.key are the PlaceCategory.name strings we
            // attach per ReorderableItem below. Translate back to the
            // enum and push a single move through the ViewModel —
            // DataStore re-emits the new order, the list recomposes,
            // and the drag ghost follows along.
            val fromCategory = (from.key as? String)?.let { runCatching { PlaceCategory.valueOf(it) }.getOrNull() }
            val toCategory = (to.key as? String)?.let { runCatching { PlaceCategory.valueOf(it) }.getOrNull() }
            if (fromCategory != null && toCategory != null && fromCategory != toCategory) {
                onReorder(fromCategory, toCategory)
            }
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "Customize categories",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        "Showing $visibleCount of ${ordered.size} · drag to reorder",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                TextButton(onClick = onReset) { Text("Reset") }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(
                    onClick = { onSetAllHidden(false) },
                    label = { Text("Show all") },
                )
                AssistChip(
                    onClick = { onSetAllHidden(true) },
                    label = { Text("Hide all") },
                )
            }
            Spacer(Modifier.height(12.dp))
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 560.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                items(items = ordered, key = { it.name }) { category ->
                    ReorderableItem(reorderState, key = category.name) { isDragging ->
                        CategoryCustomizeRow(
                            category = category,
                            visible = category !in hidden,
                            isDragging = isDragging,
                            dragHandleModifier = Modifier.draggableHandle(),
                            onVisibilityChange = { newVisible ->
                                onVisibilityChange(category, newVisible)
                            },
                        )
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onDismiss) { Text("Done") }
            }
        }
    }
}

@Composable
private fun CategoryCustomizeRow(
    category: PlaceCategory,
    visible: Boolean,
    isDragging: Boolean,
    dragHandleModifier: Modifier,
    onVisibilityChange: (newVisible: Boolean) -> Unit,
) {
    val visual = category.visual()
    val containerColor = if (isDragging) {
        MaterialTheme.colorScheme.surfaceContainerHigh
    } else {
        Color.Transparent
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(containerColor)
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Drag handle on the leading edge — long-press to grab,
        // drag to move. draggableHandle() comes from the reorderable
        // library's ReorderableCollectionItemScope.
        Icon(
            imageVector = Icons.Filled.DragHandle,
            contentDescription = "Drag to reorder ${category.label}",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = dragHandleModifier.size(24.dp),
        )
        Spacer(Modifier.width(8.dp))
        Box(
            modifier = Modifier
                .size(32.dp)
                .clip(CircleShape)
                .background(visual.tint.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = visual.icon,
                contentDescription = null,
                tint = visual.tint,
                modifier = Modifier.size(18.dp),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(
            modifier = Modifier
                .weight(1f)
                .clickable { onVisibilityChange(!visible) },
        ) {
            Text(
                text = category.label,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (category.isCuisine) {
                Text(
                    text = "Cuisine",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Switch(
            checked = visible,
            onCheckedChange = { checked -> onVisibilityChange(checked) },
        )
    }
}

// Default state: no cuisine, "All", 180° cone, 5 km radius, quality
// filter on, empty search. Any deviation lights up the clear button.
private fun hasActiveFilters(state: PlacesUiState): Boolean {
    if (state.category != null) return true
    if (state.searchQuery.isNotEmpty()) return true
    if (state.coneDegrees != 180f) return true
    if (state.radiusMeters != 5_000) return true
    if (!state.qualityFilter) return true
    return false
}

// Top-level food categories under which the cuisine sub-row reveals
// itself. When the user picks, say, SUSHI from that sub-row, the UI
// treats the cuisine itself as the "selected parent" — the row still
// shows because the cuisine's own isCuisine flag is true, and we
// return to the food bucket when the user picks "Any" from the sub-row.
private val FOOD_PARENT_CATEGORIES: Set<PlaceCategory?> =
    PlaceCategory.entries.filter { it.isCuisine }.toSet<PlaceCategory?>() +
        setOf(PlaceCategory.RESTAURANT, PlaceCategory.FAST_FOOD, PlaceCategory.BAKERY)

// ~24 dp at typical densities — below this offset "at the top" still
// reads as "at the top" even after a tiny overshoot / spring settle.
private const val TOP_EXPAND_THRESHOLD_PX: Int = 40

// Minimum scroll delta between reads before the collapse/expand
// toggle flips. Stops a one-pixel wobble (fling physics, IME push)
// from flapping the filter bar open-closed-open.
private const val SCROLL_HYSTERESIS_PX: Int = 16

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun CategoryChips(
    selected: PlaceCategory?,
    hidden: Set<PlaceCategory>,
    ordered: List<PlaceCategory>,
    onSelect: (PlaceCategory?) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // "All" is pinned on the leading edge so the reset option
        // stays visible no matter how far the user has horizontally
        // scrolled through the other categories. null selection = All.
        FilterChip(
            selected = selected == null,
            onClick = { onSelect(null) },
            label = { Text("All") },
            leadingIcon = {
                Icon(
                    Icons.Filled.AutoAwesome,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                )
            },
            colors = FilterChipDefaults.filterChipColors(),
        )
        Row(
            modifier = Modifier
                .weight(1f)
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ordered.forEach { category ->
                if (category.isCuisine) return@forEach
                if (category in hidden) return@forEach
                val visual = category.visual()
                FilterChip(
                    selected = category == selected,
                    onClick = { onSelect(category) },
                    label = { Text(category.label) },
                    leadingIcon = {
                        Icon(
                            visual.icon,
                            contentDescription = null,
                            tint = visual.tint,
                            modifier = Modifier.size(16.dp),
                        )
                    },
                    colors = FilterChipDefaults.filterChipColors(),
                )
            }
        }
    }
}

// Second chip row showing only the cuisine sub-slugs. Rendered just
// below CategoryChips when one of the food parents (or a cuisine
// itself) is active. "Any" clears back to RESTAURANT so the user can
// broaden again without hunting for the parent chip.
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun CuisineChips(
    selected: PlaceCategory?,
    hidden: Set<PlaceCategory>,
    ordered: List<PlaceCategory>,
    onSelect: (PlaceCategory?) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FilterChip(
            selected = selected?.isCuisine != true,
            onClick = { onSelect(PlaceCategory.RESTAURANT) },
            label = { Text("Any") },
            colors = FilterChipDefaults.filterChipColors(),
        )
        ordered.forEach { category ->
            if (!category.isCuisine) return@forEach
            if (category in hidden) return@forEach
            val visual = category.visual()
            FilterChip(
                selected = category == selected,
                onClick = { onSelect(category) },
                label = { Text(category.label) },
                leadingIcon = {
                    Icon(
                        visual.icon,
                        contentDescription = null,
                        tint = visual.tint,
                        modifier = Modifier.size(16.dp),
                    )
                },
                colors = FilterChipDefaults.filterChipColors(),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SearchField(query: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = query,
        onValueChange = onChange,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        placeholder = { Text("Search by name or address") },
        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
        singleLine = true,
    )
}

@Composable
private fun QualityFilterRow(enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Hide low-signal places",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = if (enabled) {
                    "Showing 4★+ with 100+ reviews"
                } else {
                    "Showing all, including unrated"
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = enabled, onCheckedChange = onChange)
    }
}

@Composable
private fun ConePicker(
    cone: Float,
    onChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    val options = listOf(30f, 60f, 180f)
    val labels = mapOf(30f to "±30°", 60f to "±60°", 180f to "All")
    Column(modifier = modifier) {
        Text(
            text = "Direction",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            options.forEachIndexed { index, value ->
                SegmentedButton(
                    selected = cone == value,
                    onClick = { onChange(value) },
                    shape = SegmentedButtonDefaults.itemShape(index, options.size),
                ) { Text(labels[value] ?: "") }
            }
        }
    }
}

@Composable
private fun RadiusPicker(
    radiusMeters: Int,
    onChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    // 50 km is the backend's hard cap (see gplaces_parser README —
    // `radius` is validated to `1..50000`); "All" just sends the
    // ceiling so the user gets the widest possible result set
    // without a special-case off-screen path.
    val options = listOf(1_000, 5_000, 20_000, 50_000)
    // Short labels so the "20 km" option doesn't wrap to a second
    // line inside the segmented button cell on phone widths.
    val labels = mapOf(1_000 to "1km", 5_000 to "5km", 20_000 to "20km", 50_000 to "All")
    Column(modifier = modifier) {
        Text(
            text = "Radius",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            options.forEachIndexed { index, value ->
                SegmentedButton(
                    selected = radiusMeters == value,
                    onClick = { onChange(value) },
                    shape = SegmentedButtonDefaults.itemShape(index, options.size),
                    label = {
                        Text(
                            text = labels[value] ?: "",
                            maxLines = 1,
                            softWrap = false,
                        )
                    },
                )
            }
        }
    }
}

@Composable
private fun LoadingState() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator()
    }
}

@Composable
private fun EmptyState(title: String, body: String) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PlaceList(
    listState: LazyListState,
    places: List<Place>,
    heading: Float,
    loadingMore: Boolean,
    canLoadMore: Boolean,
    onOpenMap: (Place) -> Unit,
    onCall: (String) -> Unit,
    onLoadMore: () -> Unit,
) {
    // Triggers a next-page fetch when the user scrolls within
    // LOAD_MORE_THRESHOLD of the end of the list. derivedStateOf
    // means we re-evaluate only when the scroll position changes,
    // not on every recomposition, so it's cheap even on a long list.
    val shouldLoadMore by remember {
        derivedStateOf {
            val layout = listState.layoutInfo
            val total = layout.totalItemsCount
            if (total == 0) return@derivedStateOf false
            val lastVisible = layout.visibleItemsInfo.lastOrNull()?.index ?: return@derivedStateOf false
            lastVisible >= total - LOAD_MORE_THRESHOLD
        }
    }
    LaunchedEffect(shouldLoadMore, canLoadMore, loadingMore) {
        if (shouldLoadMore && canLoadMore && !loadingMore) onLoadMore()
    }

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(items = places, key = { it.id }) { place ->
            PlaceCard(
                place = place,
                heading = heading,
                onOpenMap = { onOpenMap(place) },
                onCall = { place.phone?.let(onCall) },
            )
        }
        if (loadingMore) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 16.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp,
                    )
                }
            }
        } else if (!canLoadMore && places.isNotEmpty()) {
            // Quiet end-of-list marker so users know there isn't more
            // content hiding below a pull-to-refresh. Only shown once
            // the list has at least one row so it doesn't appear in
            // the "empty" state above.
            item {
                Text(
                    text = "End of results",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 16.dp),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
            }
        }
    }
}

// Start requesting the next page when we're within 5 items of the end
// of the list. Small enough that the user keeps flicking past the old
// end without ever seeing a stall, large enough to ride out typical
// network latency (~200 ms).
private const val LOAD_MORE_THRESHOLD: Int = 5

// Elevated card variant of the old row. Tapping anywhere on the card
// drops the user into their default maps app on the place's coords;
// an inline call button appears when the backend returned a phone number.
@Composable
private fun PlaceCard(
    place: Place,
    heading: Float,
    onOpenMap: () -> Unit,
    onCall: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpenMap),
        colors = CardDefaults.elevatedCardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
        ),
        elevation = CardDefaults.elevatedCardElevation(defaultElevation = 2.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CategoryBadge(place.category)
            Spacer(Modifier.size(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = place.name,
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 2,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (place.openNow == true) {
                        Spacer(Modifier.size(6.dp))
                        OpenChip()
                    }
                }
                // Rating line only appears when we actually have one
                // from the gplaces backend.
                place.rating?.let { rating ->
                    Spacer(Modifier.height(2.dp))
                    RatingLine(rating = rating, reviewCount = place.reviewCount)
                }
                val address = place.address
                if (!address.isNullOrBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = address,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                    )
                }
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    DirectionArrow(placeBearing = place.bearingDegrees, heading = heading)
                    Spacer(Modifier.size(6.dp))
                    Text(
                        text = formatDistance(place.distanceMeters),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (!place.phone.isNullOrBlank()) {
                IconButton(onClick = onCall) {
                    Icon(
                        Icons.Filled.Call,
                        contentDescription = "Call ${place.name}",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }
    }
}

// Five-star row — filled stars up to the rounded rating, outlined
// stars for the remainder. Followed by the numeric rating and
// review count so the user has both the visual scan and the exact
// number available at a glance.
@Composable
private fun RatingLine(rating: Float, reviewCount: Int?) {
    val filled = rating.coerceIn(0f, 5f).let { kotlin.math.round(it).toInt() }
    Row(verticalAlignment = Alignment.CenterVertically) {
        repeat(5) { i ->
            Icon(
                imageVector = if (i < filled) Icons.Filled.Star else Icons.Outlined.StarBorder,
                contentDescription = null,
                tint = if (i < filled) {
                    Color(0xFFF59E0B) // amber for filled
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.size(14.dp),
            )
        }
        Spacer(Modifier.size(6.dp))
        Text(
            text = buildString {
                append("%.1f".format(rating))
                if (reviewCount != null && reviewCount > 0) {
                    append(" · ")
                    append(formatReviewCount(reviewCount))
                }
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun OpenChip() {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(Color(0xFF10B981)) // emerald
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            text = "Open",
            style = MaterialTheme.typography.labelSmall,
            color = Color.White,
        )
    }
}

// "125" / "1.8K" / "15K" / "1.8M". The earlier version appended a
// second "K" on top of the %f format's built-in "K", producing
// values like "4.7KK" on the dashboard.
private fun formatReviewCount(n: Int): String = when {
    n < 1_000 -> n.toString()
    n < 10_000 -> "%.1f".format(n / 1_000f).removeSuffix(".0") + "K"
    n < 1_000_000 -> "${n / 1_000}K"
    n < 10_000_000 -> "%.1f".format(n / 1_000_000f).removeSuffix(".0") + "M"
    else -> "${n / 1_000_000}M"
}

// Coloured circular badge carrying the category's Material icon.
// Background is a 14 % alpha tint of the category's accent colour, so
// each badge picks up its own identity while staying legible against
// both light and dark surfaces. Matches the pattern used by the
// finance dashboard's CategoryBadge for visual consistency.
@Composable
private fun CategoryBadge(category: PlaceCategory) {
    val visual = category.visual()
    Box(
        modifier = Modifier
            .size(44.dp)
            .clip(CircleShape)
            .background(visual.tint.copy(alpha = 0.14f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = visual.icon,
            contentDescription = category.label,
            tint = visual.tint,
            modifier = Modifier.size(22.dp),
        )
    }
}

// Navigation arrow pointing up, rotated by the angle between the
// place's bearing and the user's current heading.
@Composable
private fun DirectionArrow(placeBearing: Float, heading: Float) {
    val delta = ((placeBearing - heading + 360f) % 360f)
    Icon(
        imageVector = Icons.Filled.Navigation,
        contentDescription = null,
        modifier = Modifier
            .size(14.dp)
            .rotate(delta),
        tint = MaterialTheme.colorScheme.primary,
    )
}

// Launch the place's detail panel in Google Maps — reviews, photos,
// hours, the works. The gplaces `id` is Google's FID (feature ID) in
// the form "0x<fid_hex>:0x<cid_hex>". The decimal CID (second half)
// is what `maps.google.com/?cid=<n>` routes to the full place card.
//
// When the id is missing or doesn't parse we fall back to the old
// `geo:` URI — good enough to drop a pin but without the review
// detail. Every Android maps handler accepts both shapes.
private fun launchMapsFor(context: Context, place: Place) {
    // Prefer the server-provided decimal `cid` (FEEDBACK.md §9.3);
    // fall back to parsing it out of the FID-shaped `id` for older
    // responses that pre-date that field.
    val cid = place.cid ?: parseCidFromFtid(place.id)
    val uri = if (cid != null) {
        "https://www.google.com/maps?cid=$cid".toUri()
    } else {
        val label = Uri.encode(place.name)
        "geo:0,0?q=${place.latitude},${place.longitude}($label)".toUri()
    }
    val intent = Intent(Intent.ACTION_VIEW, uri).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

// Google's FID shape is "0x<fid>:0x<cid>" (both hex). The second half
// is a 64-bit CID — maps deep links consume it in decimal. Using
// toULong because some real-world CIDs have the high bit set (> 2^63)
// and Long.parse would throw.
private fun parseCidFromFtid(id: String): String? {
    val parts = id.split(":")
    if (parts.size != 2) return null
    val hex = parts[1].removePrefix("0x").removePrefix("0X")
    if (hex.isEmpty() || hex.length > 16) return null
    return runCatching { hex.toULong(16).toString() }.getOrNull()
}

private fun launchDialer(context: Context, phone: String) {
    val intent = Intent(Intent.ACTION_DIAL, "tel:$phone".toUri()).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

private fun formatDistance(meters: Double): String = when {
    meters < 1_000 -> "${meters.toInt()} m"
    else -> "%.1f km".format(meters / 1_000)
}
