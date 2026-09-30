import 'package:flutter/material.dart';

import '../api_client.dart';
import '../sensitive_operation_confirmation.dart';
import '../ui/jiyi_components.dart';
import '../ui/jiyi_tokens.dart';
import 'family_api.dart';
import 'family_models.dart';
import 'v2_widgets.dart';

class FamilyPage extends StatefulWidget {
  const FamilyPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<FamilyPage> createState() => _FamilyPageState();
}

class _FamilyPageState extends State<FamilyPage> {
  late final FamilyApi familyApi = FamilyApi(widget.api);
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
          children: [
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
