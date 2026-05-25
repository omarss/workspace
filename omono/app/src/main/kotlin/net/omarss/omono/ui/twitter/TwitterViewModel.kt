package net.omarss.omono.ui.twitter

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.omarss.omono.feature.twitter.Country
import net.omarss.omono.feature.twitter.Tweet
import net.omarss.omono.feature.twitter.TweetsRepository
import timber.log.Timber

@HiltViewModel
class TwitterViewModel @Inject constructor(
    private val repository: TweetsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        TwitterUiState(configured = repository.isConfigured),
    )
    val uiState: StateFlow<TwitterUiState> = _uiState.asStateFlow()

    init {
        if (repository.isConfigured) {
            refresh()
        }
    }

    fun selectCountry(country: Country) {
        if (_uiState.value.country == country) return
        _uiState.update { it.copy(country = country) }
        refresh()
    }

    fun refresh() {
        if (!repository.isConfigured) return
        val country = _uiState.value.country
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, errorMessage = null) }
            val fetched = runCatching { repository.feed(country) }
                .onFailure { Timber.w(it, "tweets feed load failed") }
                .getOrNull()
            // Race guard — user may have flipped country while this
            // request was in flight; only commit if the response still
            // matches the current selection.
            _uiState.update { state ->
                if (state.country != country) {
                    state.copy(loading = false)
                } else {
                    state.copy(
                        loading = false,
                        tweets = fetched ?: state.tweets,
                        errorMessage = if (fetched == null) "Couldn't load feed" else null,
                    )
                }
            }
        }
    }
}

data class TwitterUiState(
    val country: Country = Country.KSA,
    val tweets: List<Tweet> = emptyList(),
    val loading: Boolean = false,
    val errorMessage: String? = null,
    val configured: Boolean = false,
)
