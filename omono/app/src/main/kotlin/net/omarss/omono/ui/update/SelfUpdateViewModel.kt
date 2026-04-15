package net.omarss.omono.ui.update

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import net.omarss.omono.BuildConfig
import net.omarss.omono.feature.selfupdate.DownloadState
import net.omarss.omono.feature.selfupdate.SelfUpdateNotifier
import net.omarss.omono.feature.selfupdate.SelfUpdateRepository
import net.omarss.omono.feature.selfupdate.UpdateInfo
import timber.log.Timber
import java.io.File
import javax.inject.Inject

// Owns the in-app self-update flow. The VM is created at activity
// scope (not screen scope) so the download survives navigation between
// the main screen and the places/finance sub-screens — cancelling a
// 14 MB download just because the user popped into finance would be
// an annoying UX bug.
@HiltViewModel
class SelfUpdateViewModel @Inject constructor(
    private val repository: SelfUpdateRepository,
    private val notifier: SelfUpdateNotifier,
) : ViewModel() {

    private val _state = MutableStateFlow(SelfUpdateUiState())
    val state: StateFlow<SelfUpdateUiState> = _state.asStateFlow()

    private var downloadJob: Job? = null

    init {
        checkForUpdate()
    }

    fun checkForUpdate() {
        viewModelScope.launch {
            val info = repository.check(BuildConfig.VERSION_NAME)
            _state.value = _state.value.copy(
                available = info,
                canInstall = repository.canInstallPackages(),
            )
            if (info != null) {
                notifier.notifyUpdateAvailable(info)
            }
        }
    }

    fun startDownload() {
        val info = _state.value.available ?: return
        if (downloadJob?.isActive == true) return
        if (!repository.canInstallPackages()) {
            _state.value = _state.value.copy(canInstall = false)
            repository.requestInstallPermission()
            return
        }
        downloadJob = viewModelScope.launch {
            _state.value = _state.value.copy(
                downloadPercent = 0,
                downloadedApk = null,
                error = null,
            )
            runCatching {
                repository.download(info).collect { event ->
                    when (event) {
                        is DownloadState.InProgress -> {
                            _state.value = _state.value.copy(downloadPercent = event.percent)
                        }
                        is DownloadState.Done -> {
                            _state.value = _state.value.copy(
                                downloadPercent = 100,
                                downloadedApk = event.apk,
                            )
                            repository.install(event.apk)
                        }
                    }
                }
            }.onFailure {
                Timber.w(it, "self-update download failed")
                _state.value = _state.value.copy(
                    downloadPercent = null,
                    error = it.message ?: "Download failed",
                )
            }
        }
    }

    fun installNow() {
        val apk = _state.value.downloadedApk ?: return
        repository.install(apk)
    }

    fun dismiss() {
        _state.value = _state.value.copy(dismissed = true)
        notifier.cancel()
    }

    fun grantInstallPermission() {
        repository.requestInstallPermission()
    }

    fun refreshPermission() {
        _state.value = _state.value.copy(canInstall = repository.canInstallPackages())
    }
}

data class SelfUpdateUiState(
    val available: UpdateInfo? = null,
    val downloadPercent: Int? = null,
    val downloadedApk: File? = null,
    val canInstall: Boolean = true,
    val dismissed: Boolean = false,
    val error: String? = null,
) {
    val showBanner: Boolean
        get() = available != null && !dismissed
    val isDownloading: Boolean
        get() = downloadPercent != null && downloadPercent < 100 && downloadedApk == null
}
