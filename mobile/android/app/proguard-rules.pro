# Huawei Mobile Services probes this vendor-only framework class on Huawei devices.
# It is intentionally absent from the public Android SDK and from non-Huawei builds.
# Keep R8 strict for all other missing classes; suppress only this known optional probe.
-dontwarn com.huawei.android.os.BuildEx$VERSION
