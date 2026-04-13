# Keep Hilt-generated code; R8 otherwise strips reflectively-used symbols.
-keep class dagger.hilt.** { *; }
-keep class * extends dagger.hilt.android.internal.managers.** { *; }

# Kotlin metadata — needed by Hilt / reflection consumers.
-keep class kotlin.Metadata { *; }
