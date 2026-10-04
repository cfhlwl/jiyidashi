import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:amap_flutter_base/amap_flutter_base.dart';
import 'package:amap_flutter_map/amap_flutter_map.dart';

import 'footprint_models.dart';

const _amapAndroidKey =
    String.fromEnvironment('AMAP_ANDROID_SDK_KEY', defaultValue: '');
const _amapIosKey =
    String.fromEnvironment('AMAP_IOS_SDK_KEY', defaultValue: '');

class JiYiAmapConfig {
  const JiYiAmapConfig({
    this.androidKey = _amapAndroidKey,
    this.iosKey = _amapIosKey,
  });

  final String androidKey;
  final String iosKey;

  bool get configuredForCurrentPlatform => switch (defaultTargetPlatform) {
        TargetPlatform.android => androidKey.trim().isNotEmpty,
        TargetPlatform.iOS => iosKey.trim().isNotEmpty,
        _ => false,
      };

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
            title: (index + 1).toString() + '. ' + widget.visits[index].placeName,
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
    return AMapWidget(
      apiKey: widget.config.apiKey,
      privacyStatement: const AMapPrivacyStatement(
        hasContains: true,
        hasShow: true,
        hasAgree: true,
      ),
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
