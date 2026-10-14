import 'package:flutter/material.dart';

import 'api_client.dart';

/// AUTH-006 read-only account security surface.
///
/// Link/unlink is deliberately disabled until a real provider and recent
/// re-authentication proof are available. Tests may exercise the typed client
/// adapter with a fake HTTP provider, but production UI never treats that fake
/// as a capability.
class AccountSecurityPage extends StatefulWidget {
  const AccountSecurityPage({
    super.key,
    required this.api,
    this.providerLinkEnabled = false,
  });

  final JiYiApiClient api;
  final bool providerLinkEnabled;

  @override
  State<AccountSecurityPage> createState() => _AccountSecurityPageState();
}

class _AccountSecurityPageState extends State<AccountSecurityPage> {
  int _generation = 0;
  int? _sessionVersion;
  String? _owner;
  bool _loading = true;
  String? _error;
  List<AuthIdentityRead> _identities = const [];

  @override
  void initState() {
    super.initState();
    _reload();
  }

  bool _current(int generation, int? sessionVersion, String? owner) =>
      mounted &&
      generation == _generation &&
      widget.api.sessionVersion == sessionVersion &&
      widget.api.authenticatedUserId == owner;

  Future<void> _reload() async {
    final generation = ++_generation;
    final sessionVersion = widget.api.sessionVersion;
    final owner = widget.api.authenticatedUserId;
    setState(() {
      _loading = true;
      _error = null;
      _sessionVersion = sessionVersion;
      _owner = owner;
    });
    try {
      final identities = await widget.api.fetchAuthIdentities();
      if (!_current(generation, sessionVersion, owner)) return;
      setState(() {
        _identities = identities;
        _loading = false;
      });
    } catch (error) {
      if (!_current(generation, sessionVersion, owner)) return;
      setState(() {
        _loading = false;
        _error = _safeError(error);
        _identities = const [];
      });
    }
  }

  String _safeError(Object error) {
    if (error is ApiException) {
      if (error.statusCode == 401) return '登录状态已失效，请重新登录';
      if (error.statusCode == 403) return '当前账号没有管理身份的权限';
      if (error.statusCode == 423) return '账号注销进行中，暂不能管理登录方式';
      if (error.statusCode == 429) return '操作过于频繁，请稍后再试';
      if (error.statusCode >= 500) return '服务暂不可用，请稍后重试';
    }
    if (error is TransportException) return '网络不可用，请检查连接后重试';
    if (error is ProtocolException) return '服务返回异常，请稍后重试';
    return '暂时无法读取登录身份，请稍后重试';
  }

  String _providerName(String provider) => switch (provider) {
        'EMAIL_PASSWORD' => '邮箱密码',
        'PHONE' => '手机号',
        'WECHAT' => '微信',
        'WECHAT_MINIPROGRAM' => '微信小程序',
        _ => '其他登录方式',
      };

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('账号与安全')),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              '登录身份',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            const Text('以下信息来自服务器身份列表，不从个人资料推断。完整手机号、openid、unionid 和凭证不会展示。'),
            const SizedBox(height: 16),
            if (_loading)
              const Center(child: Padding(
                padding: EdgeInsets.all(32),
                child: CircularProgressIndicator(),
              ))
            else if (_error != null)
              _ErrorCard(message: _error!, onRetry: _reload)
            else if (_identities.isEmpty)
              const Card(child: Padding(
                padding: EdgeInsets.all(20),
                child: Text('当前没有可展示的登录身份。'),
              ))
            else
              ..._identities.map(_identityCard),
            const SizedBox(height: 16),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('绑定与解绑', style: TextStyle(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    Text(widget.providerLinkEnabled
                        ? '当前操作需要真实 provider 认证和近期重新认证。'
                        : '当前未配置可用的身份绑定服务，绑定和解绑已安全禁用。'),
                    const SizedBox(height: 12),
                    FilledButton.tonal(
                      onPressed: widget.providerLinkEnabled ? () {} : null,
                      child: const Text('绑定新的登录方式'),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _identityCard(AuthIdentityRead identity) {
    final verified = identity.verifiedAt != null;
    final canManage = widget.providerLinkEnabled && identity.provider != 'UNKNOWN';
    return Card(
      key: ValueKey('account-identity-${identity.identityId}'),
      child: ListTile(
        title: Text(_providerName(identity.provider)),
        subtitle: Text('${identity.subjectHint}\n${verified ? '已验证' : '未验证'}'),
        isThreeLine: true,
        trailing: PopupMenuButton<String>(
          enabled: canManage,
          tooltip: canManage ? '管理身份' : '当前不可管理',
          onSelected: (_) {},
          itemBuilder: (_) => const [
            PopupMenuItem(value: 'unlink', child: Text('解绑')),
          ],
        ),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(message),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onRetry, child: const Text('重试')),
            ],
          ),
        ),
      );
}
