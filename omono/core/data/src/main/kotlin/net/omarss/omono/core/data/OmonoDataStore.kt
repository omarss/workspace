package net.omarss.omono.core.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStore

// Single app-wide DataStore. Features namespace their keys by prefix
// (e.g. "speed.unit") rather than creating sibling DataStores, so prefs
// stay in one file and we avoid coordinator contention.
val Context.omonoDataStore: DataStore<Preferences> by preferencesDataStore(name = "omono_prefs")
