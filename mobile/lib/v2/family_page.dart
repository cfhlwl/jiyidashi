import 'dart:io';

import 'package:flutter/material.dart';

import '../amap_footprint_map.dart';
import '../amap_privacy_consent.dart';
import '../api_client.dart';
import '../footprint_models.dart';
import '../media_presentation_cache.dart';
import '../sensitive_operation_confirmation.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_format.dart';
import '../ui/jiyi_tokens.dart';
import 'family_api.dart';
import 'family_models.dart';
import 'v2_widgets.dart';

typedef FamilyPhotoRenderer = Widget Function(File file);

class FamilyPage extends StatefulWidget {
  const FamilyPage({
    super.key,
    required this.api,
    this.mediaCache,
    this.amapPrivacyConsent,
    this.photoRenderer,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;
  final AmapPrivacyConsentAuthority? amapPrivacyConsent;
  final FamilyPhotoRenderer? photoRenderer;

  @override
  State<FamilyPage> createState() => _FamilyPageState();
}

class _FamilyPageState extends State<FamilyPage> {
  late final FamilyApi familyApi = FamilyApi(widget.api);
  late final LocalMediaCache mediaCache =
      widget.mediaCache ?? LocalMediaCache();
  late final AmapPrivacyConsentAuthority amapPrivacyConsent =
      widget.amapPrivacyConsent ?? AmapPrivacyConsentStore();
  final TextEditingController inviteToken = TextEditingController();

  V2Family? family;
  Map<String, V2FamilyPermissionGrant> grants = const {};
  V2FamilyInvite? invite;
  bool loading = true;
  bool noFamily = false;
  String? error;
  String? status;
  String? mutatingMemberId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    inviteToken.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
      status = null;
    });
    try {
      final nextFamily = await familyApi.getFamily();
      final rows = await familyApi.listPermissions();
      if (!mounted) return;
      setState(() {
        family = nextFamily;
        grants = {
          for (final item in rows) item.granteeUserId.toLowerCase(): item,
        };
        noFamily = false;
        loading = false;
      });
    } on ApiException catch (exc) {
      if (!mounted) return;
      if (exc.message == 'FAMILY_NOT_FOUND') {
        setState(() {
          family = null;
          grants = const {};
          noFamily = true;
          loading = false;
        });
      } else {
        setState(() {
          error = '家庭暂时无法加载，可以稍后重试';
          loading = false;
        });
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        error = '家庭数据暂时无法加载，可以稍后重试';
        loading = false;
      });
    }
  }

  Future<void> _createFamily() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await familyApi.createFamily();
      if (!mounted) return;
      await _load();
      if (mounted) setState(() => status = '家庭已创建');
    } catch (_) {
      if (!mounted) return;
      setState(() {
        loading = false;
        error = '家庭创建失败，可以稍后再试';
      });
    }
  }

  Future<void> _joinFamily() async {
    try {
      await familyApi.acceptInvite(inviteToken.text);
      inviteToken.clear();
      if (!mounted) return;
      await _load();
      if (mounted) setState(() => status = '已加入家庭');
    } on ArgumentError catch (exc) {
      if (mounted) setState(() => error = exc.message);
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        error = switch (exc.message) {
          'FAMILY_INVITE_INVALID' => '邀请口令无效',
          'FAMILY_INVITE_EXPIRED' => '邀请口令已过期',
          'FAMILY_INVITE_NOT_ACTIVE' => '邀请口令已经失效',
          _ => '加入家庭失败，可以稍后再试',
        };
      });
    } catch (_) {
      if (mounted) setState(() => error = '加入家庭失败，可以稍后再试');
    }
  }

  Future<void> _createInvite() async {
    try {
      final result = await familyApi.createInvite();
      if (!mounted) return;
      setState(() {
        invite = result;
        status = '邀请口令已生成';
      });
    } catch (_) {
      if (mounted) setState(() => error = '邀请口令暂时无法生成');
    }
  }

  bool _sameSession(int version, String ownerUserId) {
    return widget.api.sessionVersion == version &&
        widget.api.authenticatedUserId?.toLowerCase() ==
            ownerUserId.toLowerCase();
  }

  Future<void> _toggle(
    V2FamilyMember member,
    String permission,
    bool enabled,
  ) async {
    if (mutatingMemberId != null) return;
    final ownerUserId = widget.api.authenticatedUserId?.trim();
    if (ownerUserId == null || ownerUserId.isEmpty) return;
    final sessionVersion = widget.api.sessionVersion;
    final key = member.userId.toLowerCase();

    // SEC-014: single-flight begins before the dialog. A double tap cannot create
    // two confirmation/mutation chains for the same stale rendered state.
    setState(() {
      mutatingMemberId = key;
      error = null;
      status = null;
    });

    try {
      final confirmed = await showSensitiveOperationConfirmation(
        context,
        SensitiveOperationSpec.familyPermission(
          enabled: enabled,
          permissionLabel: familyPermissionLabel(permission),
          memberLabel: '该家庭成员',
        ),
      );
      if (!mounted || !confirmed) return;
      if (!_sameSession(sessionVersion, ownerUserId)) {
        setState(() {
          error = '状态刚刚发生变化，请重新打开后再试';
        });
        return;
      }

      // PUT is complete replacement. Re-read membership and the grant matrix
      // after confirmation; never derive the payload from the old switch state.
      final latestFamily = await familyApi.getFamily();
      if (!mounted || !_sameSession(sessionVersion, ownerUserId)) return;
      final targetStillExists = latestFamily.members.any(
        (item) => item.userId.toLowerCase() == key,
      );
      if (!targetStillExists) {
        setState(() {
          error = '状态刚刚发生变化，请重新打开后再试';
        });
        return;
      }

      final rows = await familyApi.listPermissions();
      if (!mounted || !_sameSession(sessionVersion, ownerUserId)) return;
      var current = V2FamilyPermissionGrant(
        granteeUserId: member.userId,
        permissions: const [],
      );
      for (final row in rows) {
        if (row.granteeUserId.toLowerCase() == key) {
          current = row;
          break;
        }
      }

      if (current.has(permission) == enabled) {
        setState(() {
          family = latestFamily;
          grants = {
            for (final item in rows) item.granteeUserId.toLowerCase(): item,
          };
          status = '当前授权状态已经是最新状态';
        });
        return;
      }

      final saved = await familyApi.replacePermissions(
        current.toggle(permission, enabled),
      );
      if (!mounted || !_sameSession(sessionVersion, ownerUserId)) return;
      final nextGrants = {
        for (final item in rows) item.granteeUserId.toLowerCase(): item,
      };
      nextGrants[key] = saved;
      setState(() {
        family = latestFamily;
        grants = nextGrants;
        status = enabled ? '已允许这项家庭查看权限' : '已取消这项家庭查看权限';
      });
    } catch (exc) {
      if (!mounted || !_sameSession(sessionVersion, ownerUserId)) return;
      setState(() {
        error = sensitiveOperationSafeError(
          exc,
          fallback: '权限更新失败，请重新打开后再试',
        );
      });
    } finally {
      if (mounted && mutatingMemberId == key) {
        setState(() => mutatingMemberId = null);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return JiYiPageFrame(
      title: '家庭',
      subtitle: '每一项共享都由你明确授权，位置需要单独开启。',
      hero: const JiYiHeroHeader(
        eyebrow: '迹忆 · 家庭',
        title: '家庭',
        subtitle: '和家人共享你明确允许的内容。位置需要单独授权。',
        icon: Icons.family_restroom_outlined,
      ),
      child: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null && family == null && !noFamily
              ? V2ErrorState(message: error!, onRetry: _load)
              : noFamily
                  ? _noFamily()
                  : _familyReady(),
    );
  }

  Widget _noFamily() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (error != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.error, message: error!),
          const SizedBox(height: JiYiSpacing.md),
        ],
        const JiYiSectionHeader(
          title: '开始使用家庭',
          subtitle: '你可以创建一个家庭，或输入家人发来的邀请口令。',
        ),
        const SizedBox(height: JiYiSpacing.md),
        FilledButton.icon(
          onPressed: _createFamily,
          icon: const Icon(Icons.add_home_outlined),
          label: const Text('创建家庭'),
        ),
        const SizedBox(height: JiYiSpacing.md),
        TextField(
          controller: inviteToken,
          decoration: const InputDecoration(labelText: '家庭邀请口令'),
        ),
        const SizedBox(height: JiYiSpacing.sm),
        OutlinedButton(
          onPressed: _joinFamily,
          child: const Text('加入家庭'),
        ),
      ],
    );
  }

  Widget _familyReady() {
    final current = family!;
    final currentUserId = familyApi.currentUserId.toLowerCase();
    final others = current.members
        .where((item) => item.userId.toLowerCase() != currentUserId)
        .toList(growable: false);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (error != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.error, message: error!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        if (status != null) ...[
          JiYiStatusBanner(kind: JiYiStatusKind.success, message: status!),
          const SizedBox(height: JiYiSpacing.sm),
        ],
        if (current.currentUserRole == 'OWNER') ...[
          JiYiSectionCard(
            title: '邀请家人',
            subtitle: '口令只用于加入这个家庭，不会自动授予任何查看权限。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                OutlinedButton.icon(
                  onPressed: _createInvite,
                  icon: const Icon(Icons.person_add_alt_1_outlined),
                  label: const Text('生成邀请口令'),
                ),
                if (invite != null) ...[
                  const SizedBox(height: JiYiSpacing.sm),
                  SelectableText(invite!.token),
                  const SizedBox(height: JiYiSpacing.xs),
                  Text(
                    '有效期至：${invite!.expiresAt}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: JiYiSpacing.md),
        ],
        const JiYiSectionHeader(
          title: '家庭成员',
          subtitle: '共享权限按成员逐项设置。当前位置与其他内容分开授权。',
        ),
        const SizedBox(height: JiYiSpacing.sm),
        if (others.isEmpty)
          const JiYiEmptyState(
            icon: Icons.family_restroom_outlined,
            title: '还没有其他家庭成员',
            message: '邀请家人加入后，再决定每个人可以查看哪些内容。',
          ),
        for (var index = 0; index < others.length; index++) ...[
          _memberCard(others[index], index),
          const SizedBox(height: JiYiSpacing.md),
        ],
      ],
    );
  }

  Widget _memberCard(V2FamilyMember member, int index) {
    final key = member.userId.toLowerCase();
    final grant = grants[key] ??
        V2FamilyPermissionGrant(
          granteeUserId: member.userId,
          permissions: const [],
        );
    final pending = mutatingMemberId == key;
    return JiYiSectionCard(
      title: '家庭成员 ${index + 1}',
      subtitle: familyRoleLabel(member.role),
      child: Material(
        type: MaterialType.transparency,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            FilledButton.tonalIcon(
              key: ValueKey('family-shared-open-${member.userId}'),
              onPressed: () {
                Navigator.of(context).push<void>(
                  MaterialPageRoute<void>(
                    builder: (_) => _FamilyMemberSharedPage(
                      api: widget.api,
                      member: member,
                      memberLabel: '家庭成员 ${index + 1}',
                      mediaCache: mediaCache,
                      amapPrivacyConsent: amapPrivacyConsent,
                      photoRenderer: widget.photoRenderer,
                    ),
                  ),
                );
              },
              icon: const Icon(Icons.photo_library_outlined),
              label: const Text('查看 TA 分享给我的内容'),
            ),
            const SizedBox(height: JiYiSpacing.md),
            Text(
              '我授权给 TA',
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: JiYiSpacing.xs),
            for (final permission in interactiveFamilyPermissions)
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                title: Text(familyPermissionLabel(permission)),
                subtitle: permission == familyViewCurrentLocation
                    ? const Text('位置权限需要单独开启')
                    : null,
                value: grant.has(permission),
                onChanged: pending
                    ? null
                    : (enabled) => _toggle(member, permission, enabled),
              ),
          ],
        ),
      ),
    );
  }
}


class _FamilyMemberSharedPage extends StatefulWidget {
  const _FamilyMemberSharedPage({
    required this.api,
    required this.member,
    required this.memberLabel,
    required this.mediaCache,
    required this.amapPrivacyConsent,
    this.photoRenderer,
  });

  final JiYiApiClient api;
  final V2FamilyMember member;
  final String memberLabel;
  final LocalMediaCache mediaCache;
  final AmapPrivacyConsentAuthority amapPrivacyConsent;
  final FamilyPhotoRenderer? photoRenderer;

  @override
  State<_FamilyMemberSharedPage> createState() =>
      _FamilyMemberSharedPageState();
}

class _FamilyMemberSharedPageState extends State<_FamilyMemberSharedPage> {
  late final FamilyApi familyApi = FamilyApi(widget.api);

  V2FamilyCurrentLocation? location;
  FootprintDay? footprint;
  List<V2FamilyMemory>? memories;
  List<V2FamilyPhoto>? photos;

  bool locationLoading = false;
  bool footprintLoading = false;
  bool memoriesLoading = false;
  bool photosLoading = false;
  bool mapPrivacyAccepted = false;

  String? locationError;
  String? footprintError;
  String? memoriesError;
  String? photosError;

  @override
  void initState() {
    super.initState();
    _loadMapPrivacy();
  }

  Future<void> _loadMapPrivacy() async {
    try {
      final accepted = await widget.amapPrivacyConsent.readAccepted();
      if (mounted) setState(() => mapPrivacyAccepted = accepted);
    } catch (_) {
      if (mounted) setState(() => mapPrivacyAccepted = false);
    }
  }

  bool _sessionCurrent(int version, String viewer) {
    return mounted &&
        widget.api.sessionVersion == version &&
        widget.api.authenticatedUserId?.toLowerCase() == viewer.toLowerCase();
  }

  String _errorText(Object error, String kind) {
    if (error is ApiException) {
      if (error.message == 'FAMILY_READ_NOT_AUTHORIZED') {
        return switch (kind) {
          'location' => 'TA 没有把当前位置分享给你。',
          'footprint' => 'TA 没有把今日足迹分享给你。',
          'memory' => 'TA 没有把个人记忆分享给你。',
          'photos' => 'TA 没有把照片分享给你。',
          _ => '这项家庭内容没有授权给你。',
        };
      }
      if (error.message == 'CURRENT_LOCATION_UNAVAILABLE') {
        return 'TA 的当前位置暂时不可用。';
      }
      if (error.message == 'FAMILY_PHOTO_UNAVAILABLE') {
        return '这张照片已经不可用。';
      }
    }
    if (error is TransportException) return '网络暂时不可用，可以稍后重试。';
    return '这项家庭内容暂时无法读取。';
  }

  Future<void> _readLocation() async {
    if (locationLoading) return;
    final viewer = widget.api.authenticatedUserId?.trim();
    if (viewer == null || viewer.isEmpty) return;
    final version = widget.api.sessionVersion;
    setState(() {
      locationLoading = true;
      locationError = null;
    });
    try {
      final next =
          await familyApi.getMemberCurrentLocation(widget.member.userId);
      if (!_sessionCurrent(version, viewer)) return;
      setState(() => location = next);
    } catch (error) {
      if (!_sessionCurrent(version, viewer)) return;
      setState(() {
        location = null;
        locationError = _errorText(error, 'location');
      });
    } finally {
      if (_sessionCurrent(version, viewer)) {
        setState(() => locationLoading = false);
      }
    }
  }

  Future<void> _readFootprint() async {
    if (footprintLoading) return;
    final viewer = widget.api.authenticatedUserId?.trim();
    if (viewer == null || viewer.isEmpty) return;
    final version = widget.api.sessionVersion;
    setState(() {
      footprintLoading = true;
      footprintError = null;
    });
    try {
      final next =
          await familyApi.getMemberTodayFootprint(widget.member.userId);
      if (!_sessionCurrent(version, viewer)) return;
      setState(() => footprint = next);
    } catch (error) {
      if (!_sessionCurrent(version, viewer)) return;
      setState(() {
        footprint = null;
        footprintError = _errorText(error, 'footprint');
      });
    } finally {
      if (_sessionCurrent(version, viewer)) {
        setState(() => footprintLoading = false);
      }
    }
  }

  Future<void> _readMemories() async {
    if (memoriesLoading) return;
    final viewer = widget.api.authenticatedUserId?.trim();
    if (viewer == null || viewer.isEmpty) return;
    final version = widget.api.sessionVersion;
    setState(() {
      memoriesLoading = true;
      memoriesError = null;
    });
    try {
      final next = await familyApi.getMemberMemories(
        widget.member.userId,
        limit: 8,
      );
      if (!_sessionCurrent(version, viewer)) return;
      setState(() => memories = next);
    } catch (error) {
      if (!_sessionCurrent(version, viewer)) return;
      setState(() {
        memories = null;
        memoriesError = _errorText(error, 'memory');
      });
    } finally {
      if (_sessionCurrent(version, viewer)) {
        setState(() => memoriesLoading = false);
      }
    }
  }

  Future<void> _readPhotos() async {
    if (photosLoading) return;
    final viewer = widget.api.authenticatedUserId?.trim();
    if (viewer == null || viewer.isEmpty) return;
    final version = widget.api.sessionVersion;
    setState(() {
      photosLoading = true;
      photosError = null;
    });
    try {
      final next = await familyApi.getMemberPhotos(widget.member.userId);
      if (!_sessionCurrent(version, viewer)) return;
      for (final photo in next) {
        widget.mediaCache.markAuthorityValidated(
          ownerUserId: viewer,
          mediaId: familyMediaCacheKey(widget.member.userId, photo.mediaId),
        );
      }
      setState(() => photos = next);
    } on ApiException catch (error) {
      if (!_sessionCurrent(version, viewer)) return;
      if (error.statusCode == 403 || error.statusCode == 404) {
        await widget.mediaCache.invalidateMediaPrefix(
          ownerUserId: viewer,
          mediaIdPrefix: '${widget.member.userId.toLowerCase()}_',
        );
      }
      if (!_sessionCurrent(version, viewer)) return;
      setState(() {
        photos = null;
        photosError = _errorText(error, 'photos');
      });
    } catch (error) {
      if (!_sessionCurrent(version, viewer)) return;
      setState(() {
        photos = null;
        photosError = _errorText(error, 'photos');
      });
    } finally {
      if (_sessionCurrent(version, viewer)) {
        setState(() => photosLoading = false);
      }
    }
  }

  Future<void> _acceptMapPrivacy() async {
    final accepted = await requestAmapPrivacyConsent(
      context,
      widget.amapPrivacyConsent,
    );
    if (mounted && accepted) setState(() => mapPrivacyAccepted = true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.memberLabel)),
      body: SafeArea(
        child: JiYiPageFrame(
          title: '家人分享',
          subtitle: '只显示 TA 明确授权给你的内容；没有授权时不会从其他数据推断。',
          hero: JiYiHeroHeader(
            eyebrow: '迹忆 · 家庭',
            title: widget.memberLabel,
            subtitle: '照片、位置、足迹和记忆分别授权，随时以服务端当前权限为准。',
            icon: Icons.family_restroom_outlined,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _photosSection(),
              const SizedBox(height: JiYiSpacing.lg),
              _locationSection(),
              const SizedBox(height: JiYiSpacing.lg),
              _footprintSection(),
              const SizedBox(height: JiYiSpacing.lg),
              _memorySection(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _photosSection() {
    final current = photos;
    return JiYiSectionCard(
      leading: const Icon(Icons.photo_library_outlined),
      title: 'TA 分享的照片',
      subtitle: '照片优先从本机受控缓存展示；授权变化后会重新验证。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          FilledButton.tonalIcon(
            key: const ValueKey('family-read-photos'),
            onPressed: photosLoading ? null : _readPhotos,
            icon: photosLoading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.photo_outlined),
            label: Text(photosLoading ? '正在读取…' : '查看照片'),
          ),
          if (photosError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              message: photosError!,
            ),
          ],
          if (current != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            if (current.isEmpty)
              const JiYiEmptyState(
                icon: Icons.photo_outlined,
                title: '暂时没有可分享的照片',
                message: 'TA 后续分享的照片会显示在这里。',
              )
            else
              GridView.builder(
                key: const ValueKey('family-photo-grid'),
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                itemCount: current.length > 6 ? 6 : current.length,
                gridDelegate:
                    const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 2,
                  crossAxisSpacing: JiYiSpacing.sm,
                  mainAxisSpacing: JiYiSpacing.sm,
                  childAspectRatio: 1.15,
                ),
                itemBuilder: (context, index) => _FamilyPhotoTile(
                  api: widget.api,
                  familyApi: familyApi,
                  resourceOwnerUserId: widget.member.userId,
                  photo: current[index],
                  mediaCache: widget.mediaCache,
                  renderer: widget.photoRenderer,
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _locationSection() {
    final current = location;
    return JiYiSectionCard(
      leading: const Icon(Icons.my_location_outlined),
      title: '当前位置',
      subtitle: '只有 TA 单独授权且服务端判定位置仍新鲜时才会显示。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(
            key: const ValueKey('family-read-location'),
            onPressed: locationLoading ? null : _readLocation,
            icon: locationLoading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.place_outlined),
            label: Text(locationLoading ? '正在读取…' : '查看当前位置'),
          ),
          if (locationError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              message: locationError!,
            ),
          ],
          if (current != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            Text(
              '更新于 ${jiyiDisplayTime(current.recordedAt)}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: JiYiSpacing.sm),
            if (mapPrivacyAccepted)
              JiYiPlaceMap(
                latitude: current.latitude,
                longitude: current.longitude,
                name: widget.memberLabel,
                address: '家人明确授权的当前位置',
                privacyAccepted: true,
              )
            else
              OutlinedButton.icon(
                key: const ValueKey('family-amap-privacy-accept'),
                onPressed: _acceptMapPrivacy,
                icon: const Icon(Icons.map_outlined),
                label: const Text('查看地图服务说明并启用地图'),
              ),
          ],
        ],
      ),
    );
  }

  Widget _footprintSection() {
    final current = footprint;
    return JiYiSectionCard(
      leading: const Icon(Icons.route_outlined),
      title: '今日足迹',
      subtitle: '只展示服务端已经形成的到访片段，不用当前位置补全路线。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(
            key: const ValueKey('family-read-footprint'),
            onPressed: footprintLoading ? null : _readFootprint,
            icon: footprintLoading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.route_outlined),
            label: Text(footprintLoading ? '正在读取…' : '查看今日足迹'),
          ),
          if (footprintError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              message: footprintError!,
            ),
          ],
          if (current != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            if (current.visits.isEmpty)
              const JiYiEmptyState(
                icon: Icons.location_off_outlined,
                title: '今天还没有形成足迹',
                message: '没有可靠到访时不会补造地点。',
              )
            else
              for (var index = 0; index < current.visits.length; index++) ...[
                _FamilyFootprintRow(visit: current.visits[index]),
                if (index != current.visits.length - 1)
                  const Divider(height: JiYiSpacing.lg),
              ],
          ],
        ],
      ),
    );
  }

  Widget _memorySection() {
    final current = memories;
    return JiYiSectionCard(
      leading: const Icon(Icons.auto_stories_outlined),
      title: 'TA 分享的记忆',
      subtitle: '这里是 Family-safe 只读投影，不包含内部 metadata 或原始位置点。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(
            key: const ValueKey('family-read-memories'),
            onPressed: memoriesLoading ? null : _readMemories,
            icon: memoriesLoading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.auto_stories_outlined),
            label: Text(memoriesLoading ? '正在读取…' : '查看个人记忆'),
          ),
          if (memoriesError != null) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              message: memoriesError!,
            ),
          ],
          if (current != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            if (current.isEmpty)
              const JiYiEmptyState(
                icon: Icons.auto_stories_outlined,
                title: '暂时没有可分享的记忆',
                message: 'TA 分享的记忆会显示在这里。',
              )
            else
              for (var index = 0; index < current.length; index++) ...[
                _FamilyMemoryCard(memory: current[index]),
                if (index != current.length - 1)
                  const SizedBox(height: JiYiSpacing.sm),
              ],
          ],
        ],
      ),
    );
  }
}

class _FamilyPhotoTile extends StatefulWidget {
  const _FamilyPhotoTile({
    required this.api,
    required this.familyApi,
    required this.resourceOwnerUserId,
    required this.photo,
    required this.mediaCache,
    this.renderer,
  });

  final JiYiApiClient api;
  final FamilyApi familyApi;
  final String resourceOwnerUserId;
  final V2FamilyPhoto photo;
  final LocalMediaCache mediaCache;
  final FamilyPhotoRenderer? renderer;

  @override
  State<_FamilyPhotoTile> createState() => _FamilyPhotoTileState();
}

class _FamilyPhotoTileState extends State<_FamilyPhotoTile> {
  File? file;
  bool unavailable = false;
  int generation = 0;

  @override
  void initState() {
    super.initState();
    _resolve();
  }

  @override
  void didUpdateWidget(covariant _FamilyPhotoTile oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.photo.mediaId != widget.photo.mediaId ||
        oldWidget.photo.cacheVersion != widget.photo.cacheVersion ||
        oldWidget.resourceOwnerUserId != widget.resourceOwnerUserId) {
      _resolve();
    }
  }

  bool _current(int attempt, int sessionVersion, String viewer) {
    return mounted &&
        generation == attempt &&
        widget.api.sessionVersion == sessionVersion &&
        widget.api.authenticatedUserId?.toLowerCase() == viewer.toLowerCase();
  }

  Future<void> _resolve() async {
    final attempt = ++generation;
    final viewer = widget.api.authenticatedUserId?.trim();
    if (viewer == null || viewer.isEmpty) return;
    final sessionVersion = widget.api.sessionVersion;
    final mediaKey = familyMediaCacheKey(
      widget.resourceOwnerUserId,
      widget.photo.mediaId,
    );
    try {
      final cached = await widget.mediaCache.lookup(
        ownerUserId: viewer,
        mediaId: mediaKey,
        cacheVersion: widget.photo.cacheVersion,
      );
      if (!_current(attempt, sessionVersion, viewer)) return;
      if (cached != null &&
          widget.mediaCache.hasFreshAuthorityLease(
            ownerUserId: viewer,
            mediaId: mediaKey,
          )) {
        setState(() {
          file = cached;
          unavailable = false;
        });
        return;
      }

      final signed = await widget.familyApi.createMemberPhotoDownload(
        widget.resourceOwnerUserId,
        widget.photo.mediaId,
      );
      if (!_current(attempt, sessionVersion, viewer)) return;
      final bytes = await widget.api.downloadSignedMedia(signed.download);
      if (!_current(attempt, sessionVersion, viewer)) return;
      final stored = await widget.mediaCache.putBytes(
        ownerUserId: viewer,
        mediaId: mediaKey,
        cacheVersion: widget.photo.cacheVersion,
        bytes: bytes,
      );
      widget.mediaCache.markAuthorityValidated(
        ownerUserId: viewer,
        mediaId: mediaKey,
      );
      if (!_current(attempt, sessionVersion, viewer)) return;
      setState(() {
        file = stored;
        unavailable = false;
      });
    } on ApiException catch (error) {
      if (error.statusCode == 403 || error.statusCode == 404) {
        await widget.mediaCache.invalidateMedia(
          ownerUserId: viewer,
          mediaId: mediaKey,
        );
      }
      if (!_current(attempt, sessionVersion, viewer)) return;
      setState(() {
        file = null;
        unavailable = true;
      });
    } catch (_) {
      if (!_current(attempt, sessionVersion, viewer)) return;
      setState(() {
        file = null;
        unavailable = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final current = file;
    return ClipRRect(
      borderRadius: BorderRadius.circular(JiYiRadius.control),
      child: current == null
          ? ColoredBox(
              color: Theme.of(context).colorScheme.surfaceContainerLow,
              child: Center(
                child: Icon(
                  unavailable
                      ? Icons.image_not_supported_outlined
                      : Icons.photo_outlined,
                ),
              ),
            )
          : widget.renderer?.call(current) ??
              Image.file(
                current,
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => const Center(
                  child: Icon(Icons.broken_image_outlined),
                ),
              ),
    );
  }
}

class _FamilyFootprintRow extends StatelessWidget {
  const _FamilyFootprintRow({required this.visit});

  final FootprintVisit visit;

  @override
  Widget build(BuildContext context) {
    final end = visit.leftAtLocal == null
        ? '仍在停留'
        : jiyiDisplayTime(visit.leftAtLocal!);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.place_outlined, size: 20),
        const SizedBox(width: JiYiSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                visit.placeName,
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                '${jiyiDisplayTime(visit.arrivedAtLocal)} · $end',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _FamilyMemoryCard extends StatelessWidget {
  const _FamilyMemoryCard({required this.memory});

  final V2FamilyMemory memory;

  @override
  Widget build(BuildContext context) {
    final title = memory.title?.trim();
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(JiYiRadius.control),
      ),
      child: Padding(
        padding: const EdgeInsets.all(JiYiSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title == null || title.isEmpty ? '一段记忆' : title,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: JiYiSpacing.xs),
            if (memory.content.trim().isNotEmpty)
              Text(
                memory.content,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            const SizedBox(height: JiYiSpacing.xs),
            Text(
              jiyiDisplayDate(memory.occurredAt),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
