package net.omarss.omono.feature.speed.trips

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Database(entities = [TripEntity::class], version = 1, exportSchema = false)
abstract class SpeedDatabase : RoomDatabase() {
    abstract fun tripDao(): TripDao
}

@Module
@InstallIn(SingletonComponent::class)
object SpeedDatabaseModule {

    @Provides
    @Singleton
    fun provideSpeedDatabase(@ApplicationContext context: Context): SpeedDatabase =
        Room.databaseBuilder(context, SpeedDatabase::class.java, "omono-speed.db")
            .fallbackToDestructiveMigration(dropAllTables = true)
            .build()

    @Provides
    fun provideTripDao(db: SpeedDatabase): TripDao = db.tripDao()
}
