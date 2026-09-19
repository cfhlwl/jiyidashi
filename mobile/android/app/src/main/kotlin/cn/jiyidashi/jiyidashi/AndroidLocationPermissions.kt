package cn.jiyidashi.jiyidashi

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build

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
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

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
