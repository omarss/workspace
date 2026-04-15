package net.omarss.omono.feature.selfupdate

// SemVer-ish comparator that tolerates trailing suffixes ("1.2.3-rc1")
// by comparing only the leading dotted integer triple. Anything that
// isn't a number collapses to 0, which is good enough for the personal
// apps-host manifest where every version is strict MAJOR.MINOR.PATCH.
internal fun compareVersions(a: String, b: String): Int {
    val aParts = a.splitVersion()
    val bParts = b.splitVersion()
    val size = maxOf(aParts.size, bParts.size)
    for (i in 0 until size) {
        val ai = aParts.getOrElse(i) { 0 }
        val bi = bParts.getOrElse(i) { 0 }
        if (ai != bi) return ai.compareTo(bi)
    }
    return 0
}

private fun String.splitVersion(): List<Int> =
    substringBefore('-')
        .substringBefore('+')
        .split('.')
        .map { it.toIntOrNull() ?: 0 }
