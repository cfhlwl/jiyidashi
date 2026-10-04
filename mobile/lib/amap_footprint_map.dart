import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:csp_amap_flutter_map/base/csp_amap_flutter_base.dart';
import 'package:csp_amap_flutter_map/csp_amap_flutter_map.dart';

import 'footprint_models.dart';

const _amapAndroidKey =
    String.fromEnvironment('AMAP_ANDROID_SDK_KEY', defaultValue: '');
const _amapIosKey =
    String.fromEnvironment('AMAP_IOS_SDK_KEY', defaultValue: '');
const _appEnv = String.fromEnvironment('APP_ENV', defaultValue: 'development');

typedef JiYiAmapPrivacyUpdater = void Function(AMapPrivacyStatement statement);
typedef JiYiAmapInitializer = void Function(
  BuildContext context, {
  required AMapApiKey apiKey,
});

class JiYiAmapSdkHooks {
  const JiYiAmapSdkHooks({
    required this.updatePrivacyAgree,
    required this.init,
  });

  final JiYiAmapPrivacyUpdater updatePrivacyAgree;
  final JiYiAmapInitializer init;
}

void bootstrapJiYiAmapSdk(
  BuildContext context,
  JiYiAmapConfig config, {
  JiYiAmapSdkHooks hooks = const JiYiAmapSdkHooks(
    updatePrivacyAgree: AMapInitializer.updatePrivacyAgree,
    init: AMapInitializer.init,
  ),
}) {
  hooks.updatePrivacyAgree(
    const AMapPrivacyStatement(
      hasContains: true,
      hasShow: true,
      hasAgree: true,
    ),
  );
  hooks.init(context, apiKey: config.apiKey);
}

class JiYiAmapConfig {
  const JiYiAmapConfig({
    this.androidKey = _amapAndroidKey,
    this.iosKey = _amapIosKey,
    this.platformOverride,
    this.appEnv = _appEnv,
  });

  final String androidKey;
  final String iosKey;
  final TargetPlatform? platformOverride;
  final String appEnv;

  bool get isProduction => appEnv.trim().toLowerCase() == 'production';

  bool get configuredForCurrentPlatform =>
      switch (platformOverride ?? defaultTargetPlatform) {
        TargetPlatform.android => androidKey.trim().isNotEmpty,
        TargetPlatform.iOS => iosKey.trim().isNotEmpty,
        _ => false,
      };

  void assertProductionConfiguration() {
    final platform = platformOverride ?? defaultTargetPlatform;
    final mapCapable =
        platform == TargetPlatform.android || platform == TargetPlatform.iOS;
    if (isProduction && mapCapable && !configuredForCurrentPlatform) {
      throw StateError(
        'Production AMap configuration is missing the platform SDK key.',
      );
    }
  }

  AMapApiKey get apiKey => AMapApiKey(
        androidKey: androidKey.trim().isEmpty ? null : androidKey.trim(),
        iosKey: iosKey.trim().isEmpty ? null : iosKey.trim(),
      );
}

typedef JiYiAmapNativeBuilder = Widget Function(
  BuildContext context,
  JiYiAmapConfig config,
  List<FootprintVisit> visits,
  int selectedIndex,
  ValueChanged<int> onSelected,
  bool interactive,
);

class JiYiFootprintMap extends StatelessWidget {
  const JiYiFootprintMap({
    super.key,
    required this.visits,
    required this.privacyAccepted,
    required this.selectedIndex,
    required this.onSelected,
    this.interactive = true,
    this.config = const JiYiAmapConfig(),
    this.nativeBuilder,
  });

  final List<FootprintVisit> visits;
  final bool privacyAccepted;
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final bool interactive;
  final JiYiAmapConfig config;
  final JiYiAmapNativeBuilder? nativeBuilder;

  @override
  Widget build(BuildContext context) {
    config.assertProductionConfiguration();
    final mappable = visits.where((visit) => visit.isMappable).toList(growable: false);
    if (mappable.isEmpty) {
      return const _MapFallback(
        key: ValueKey('amap-no-coordinate'),
        icon: Icons.location_off_outlined,
        title: '这些足迹暂时没有可用坐标',
        message: '地点和时间仍会照常显示，不会为了地图效果补造位置。',
      );
    }
    if (!privacyAccepted) {
      return const _MapFallback(
        key: ValueKey('amap-privacy-blocked'),
        icon: Icons.privacy_tip_outlined,
        title: '地图尚未启用',
        message: '同意应用隐私政策中的高德地图服务说明后，才会初始化地图 SDK。地点文字仍可正常查看。',
      );
    }
    if (!config.configuredForCurrentPlatform) {
      return const _MapFallback(
        key: ValueKey('amap-key-unavailable'),
        icon: Icons.map_outlined,
        title: '地图服务暂不可用',
        message: '当前安装包没有配置本平台地图 SDK Key。地点和时间信息仍可正常查看。',
      );
    }

    final safeSelected =
        selectedIndex >= 0 && selectedIndex < mappable.length ? selectedIndex : 0;
    final builder = nativeBuilder ?? _defaultNativeBuilder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: SizedBox(
        key: const ValueKey('amap-real-surface'),
        height: interactive ? 360 : 210,
        child: builder(
          context,
          config,
          mappable,
          safeSelected,
          onSelected,
          interactive,
        ),
      ),
    );
  }
}

Widget _defaultNativeBuilder(
  BuildContext context,
  JiYiAmapConfig config,
  List<FootprintVisit> visits,
  int selectedIndex,
  ValueChanged<int> onSelected,
  bool interactive,
) {
  return _NativeFootprintMap(
    config: config,
    visits: visits,
    selectedIndex: selectedIndex,
    onSelected: onSelected,
    interactive: interactive,
  );
}

class _NativeFootprintMap extends StatefulWidget {
  const _NativeFootprintMap({
    required this.config,
    required this.visits,
    required this.selectedIndex,
    required this.onSelected,
    required this.interactive,
  });

  final JiYiAmapConfig config;
  final List<FootprintVisit> visits;
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final bool interactive;

  @override
  State<_NativeFootprintMap> createState() => _NativeFootprintMapState();
}

class _NativeFootprintMapState extends State<_NativeFootprintMap> {
  AMapController? _controller;

  @override
  void didUpdateWidget(covariant _NativeFootprintMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.visits != widget.visits) {
      _fitCamera();
    }
  }

  @override
  void dispose() {
    _controller?.disponse();
    _controller = null;
    super.dispose();
  }

  Set<Marker> get _markers {
    return <Marker>{
      for (var index = 0; index < widget.visits.length; index++)
        Marker(
          position: LatLng(
            widget.visits[index].latitude!,
            widget.visits[index].longitude!,
          ),
          icon: BitmapDescriptor.defaultMarkerWithHue(
            index == widget.selectedIndex
                ? BitmapDescriptor.hueOrange
                : BitmapDescriptor.hueAzure,
          ),
          infoWindow: InfoWindow(
            title: '${index + 1}. ${widget.visits[index].placeName}',
            snippet: widget.visits[index].address,
          ),
          onTap: (_) => widget.onSelected(index),
        ),
    };
  }

  Set<Polyline> get _connectors {
    if (widget.visits.length < 2) return const <Polyline>{};
    return <Polyline>{
      Polyline(
        points: widget.visits
            .map((visit) => LatLng(visit.latitude!, visit.longitude!))
            .toList(growable: false),
        width: 4,
        color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.55),
      ),
    };
  }

  Future<void> _fitCamera() async {
    final controller = _controller;
    if (controller == null || widget.visits.isEmpty) return;

    if (widget.visits.length == 1) {
      final visit = widget.visits.single;
      await controller.moveCamera(
        CameraUpdate.newLatLngZoom(
          LatLng(visit.latitude!, visit.longitude!),
          15,
        ),
      );
      return;
    }

    var minLat = widget.visits.first.latitude!;
    var maxLat = minLat;
    var minLng = widget.visits.first.longitude!;
    var maxLng = minLng;
    for (final visit in widget.visits.skip(1)) {
      minLat = visit.latitude! < minLat ? visit.latitude! : minLat;
      maxLat = visit.latitude! > maxLat ? visit.latitude! : maxLat;
      minLng = visit.longitude! < minLng ? visit.longitude! : minLng;
      maxLng = visit.longitude! > maxLng ? visit.longitude! : maxLng;
    }

    await controller.moveCamera(
      CameraUpdate.newLatLngBounds(
        LatLngBounds(
          southwest: LatLng(minLat, minLng),
          northeast: LatLng(maxLat, maxLng),
        ),
        44,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    bootstrapJiYiAmapSdk(context, widget.config);
    return AMapWidget(
      initialCameraPosition: CameraPosition(
        target: LatLng(
          widget.visits.first.latitude!,
          widget.visits.first.longitude!,
        ),
        zoom: 14,
      ),
      markers: _markers,
      polylines: _connectors,
      scrollGesturesEnabled: widget.interactive,
      zoomGesturesEnabled: widget.interactive,
      rotateGesturesEnabled: widget.interactive,
      tiltGesturesEnabled: false,
      touchPoiEnabled: false,
      onMapCreated: (controller) {
        _controller = controller;
        _fitCamera();
      },
    );
  }
}

typedef JiYiPlaceNativeBuilder = Widget Function(
  BuildContext context,
  JiYiAmapConfig config,
  double latitude,
  double longitude,
  String name,
  String? address,
);

class JiYiPlaceMap extends StatelessWidget {
  const JiYiPlaceMap({
    super.key,
    required this.latitude,
    required this.longitude,
    required this.name,
    required this.privacyAccepted,
    this.address,
    this.config = const JiYiAmapConfig(),
    this.nativeBuilder,
  });

  final double? latitude;
  final double? longitude;
  final String name;
  final String? address;
  final bool privacyAccepted;
  final JiYiAmapConfig config;
  final JiYiPlaceNativeBuilder? nativeBuilder;

  bool get _validCoordinate =>
      latitude != null &&
      longitude != null &&
      latitude!.isFinite &&
      longitude!.isFinite &&
      latitude! >= -90 &&
      latitude! <= 90 &&
      longitude! >= -180 &&
      longitude! <= 180;

  @override
  Widget build(BuildContext context) {
    config.assertProductionConfiguration();
    if (!_validCoordinate) {
      return const SizedBox.shrink(
        key: ValueKey('amap-place-no-coordinate'),
      );
    }
    if (!privacyAccepted) {
      return const _MapFallback(
        key: ValueKey('amap-place-privacy-blocked'),
        icon: Icons.privacy_tip_outlined,
        title: '地图尚未启用',
        message: '同意地图服务隐私说明后才会初始化地图 SDK。',
      );
    }
    if (!config.configuredForCurrentPlatform) {
      return const _MapFallback(
        key: ValueKey('amap-place-key-unavailable'),
        icon: Icons.map_outlined,
        title: '地图服务暂不可用',
        message: '地点名称、地址和到访记录仍可正常查看。',
      );
    }

    final builder = nativeBuilder ?? _defaultPlaceNativeBuilder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: SizedBox(
        key: const ValueKey('amap-place-real-surface'),
        height: 240,
        child: builder(
          context,
          config,
          latitude!,
          longitude!,
          name,
          address,
        ),
      ),
    );
  }
}

Widget _defaultPlaceNativeBuilder(
  BuildContext context,
  JiYiAmapConfig config,
  double latitude,
  double longitude,
  String name,
  String? address,
) {
  final coordinate = LatLng(latitude, longitude);
  bootstrapJiYiAmapSdk(context, config);
  return AMapWidget(
    initialCameraPosition: CameraPosition(target: coordinate, zoom: 15),
    markers: <Marker>{
      Marker(
        position: coordinate,
        infoWindow: InfoWindow(title: name, snippet: address),
      ),
    },
    touchPoiEnabled: false,
  );
}

class _MapFallback extends StatelessWidget {
  const _MapFallback({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      constraints: const BoxConstraints(minHeight: 180),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 32, color: theme.colorScheme.primary),
          const SizedBox(height: 12),
          Text(
            title,
            textAlign: TextAlign.center,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
