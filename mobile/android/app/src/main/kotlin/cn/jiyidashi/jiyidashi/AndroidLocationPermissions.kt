package cn.jiyidashi.jiyidashi

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build

// 这里只读取 Android 的权限/系统定位能力，不拥有自动定位生命周期。
// Android Q+ 将后台权限与前台权限分离；即使权限已授予，也绝不等价于 native location producer 已启动。
internal object AndroidLocationPermissions {
    fun foregroundGranted(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        return context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    fun backgroundGranted(context: Context): Boolean {
        if (!foregroundGranted(context)) return false
        // Android 10 以前没有独立 ACCESS_BACKGROUND_LOCATION runtime grant；Q+ 才需要单独判断。
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    // requested 标记只用于区分“尚未询问”和“用户已拒绝”的展示语义，不能作为授权或采集已开始的证据。
    fun level(
        context: Context,
        store: NativeLocationStore,
    ): NativeLocationPermissionLevel {
        if (!foregroundGranted(context)) {
            return if (store.foregroundPermissionRequested) {
                NativeLocationPermissionLevel.DENIED
            } else {
                NativeLocationPermissionLevel.NOT_DETERMINED
            }
        }
        return if (backgroundGranted(context)) {
            NativeLocationPermissionLevel.BACKGROUND
        } else {
            NativeLocationPermissionLevel.FOREGROUND
        }
    }

    fun locationServicesEnabled(context: Context): Boolean {
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            manager.isLocationEnabled
        } else {
            manager.getProviders(true).isNotEmpty()
        }
    }
}
