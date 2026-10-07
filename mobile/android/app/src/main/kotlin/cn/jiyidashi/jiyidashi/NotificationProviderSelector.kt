package cn.jiyidashi.jiyidashi

internal object NotificationProviderSelector {
    fun select(
        hmsConfigured: Boolean,
        hmsAvailable: Boolean,
        fcmConfigured: Boolean,
        gmsAvailable: Boolean,
    ): String? {
        if (hmsConfigured && hmsAvailable) return "HMS"
        if (fcmConfigured && gmsAvailable) return "FCM"
        return null
    }
}
