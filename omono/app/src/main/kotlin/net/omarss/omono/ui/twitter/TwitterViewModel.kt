package net.omarss.omono.ui.twitter

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.twitter.FeedPage
import net.omarss.omono.feature.twitter.FeedRequest
import net.omarss.omono.feature.twitter.LocationCatalog
import net.omarss.omono.feature.twitter.LocationFilter
import net.omarss.omono.feature.twitter.LocationOption
import net.omarss.omono.feature.twitter.Tweet
import net.omarss.omono.feature.twitter.TweetsRepository
import timber.log.Timber

@HiltViewModel
class TwitterViewModel @Inject constructor(
    private val repository: TweetsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        TwitterUiState(
            configured = repository.isConfigured,
            filter = LocationFilter(LocationCatalog.defaults),
        ),
    )
    val uiState: StateFlow<TwitterUiState> = _uiState.asStateFlow()

    // Current in-flight network call. Cancelled on filter changes /
    // pull-to-refresh / VM destruction so a slow stale fetch can't
    // overwrite a fresh response.
    private var currentJob: Job? = null

    init {
        if (repository.isConfigured) refresh()
    }

    /** Replace the current selection. Triggers a fresh refresh. */
    fun selectLocations(newSelection: Set<LocationOption>) {
        if (_uiState.value.filter.selected == newSelection) return
        _uiState.update { it.copy(filter = LocationFilter(newSelection)) }
        refresh()
    }

    /** Toggle a single option in/out of the selection. */
    fun toggleLocation(option: LocationOption) {
        val current = _uiState.value.filter.selected.toMutableSet()
        if (option in current) current.remove(option) else current.add(option)
        selectLocations(current)
    }

    /** Show / hide the multi-select sheet. */
    fun setFilterSheetOpen(open: Boolean) {
        _uiState.update { it.copy(filterSheetOpen = open) }
    }

    /** Pull-to-refresh: drop the list, refetch from the first page. */
    fun refresh() {
        if (!repository.isConfigured) return
        currentJob?.cancel()
        _uiState.update { it.copy(loading = true, errorMessage = null) }
        currentJob = viewModelScope.launch {
            val filter = _uiState.value.filter
            val page = fetchPage(filter, cursor = null)
            if (_uiState.value.filter.selected != filter.selected) return@launch
            _uiState.update {
                it.copy(
                    loading = false,
                    loadingMore = false,
                    tweets = page?.tweets ?: emptyList(),
                    nextCursor = page?.nextCursor,
                    endReached = page == null || page.nextCursor.isNullOrBlank(),
                    errorMessage = if (page == null) "Couldn't load feed" else null,
                )
            }
        }
    }

    /** End-of-list scroll handler. Idempotent: short-circuits when
     *  no cursor is available or another load is already running. */
    fun loadMore() {
        if (!repository.isConfigured) return
        val state = _uiState.value
        if (state.loading || state.loadingMore || state.endReached) return
        val cursor = state.nextCursor ?: return
        _uiState.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            val filter = state.filter
            val page = fetchPage(filter, cursor)
            if (_uiState.value.filter.selected != filter.selected) return@launch
            _uiState.update {
                if (page == null) {
                    it.copy(loadingMore = false, errorMessage = "Couldn't load more")
                } else {
                    it.copy(
                        loadingMore = false,
                        tweets = it.tweets + page.tweets,
                        nextCursor = page.nextCursor,
                        endReached = page.nextCursor.isNullOrBlank(),
                    )
                }
            }
        }
    }

    private suspend fun fetchPage(filter: LocationFilter, cursor: String?): FeedPage? {
        val request = FeedRequest(
            countries = filter.countries,
            cities = filter.cities,
            cursor = cursor,
            limit = 60,
        )
        return runCatching { repository.feed(request) }
            .onFailure { Timber.w(it, "tweets feed load failed") }
            .getOrNull()
    }
}

data class TwitterUiState(
    val filter: LocationFilter,
    val tweets: List<Tweet> = emptyList(),
    val nextCursor: String? = null,
    val endReached: Boolean = false,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val filterSheetOpen: Boolean = false,
    val errorMessage: String? = null,
    val configured: Boolean = false,
)
