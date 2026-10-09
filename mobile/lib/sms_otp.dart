import 'dart:async';

import 'package:flutter/material.dart';

import 'auth_v3.dart';
import 'ui/jiyi_tokens.dart';

class SmsOtpRequestResult {
  const SmsOtpRequestResult({
    required this.requestId,
    required this.expiresAt,
    required this.cooldownUntil,
  });

  final String requestId;
  final DateTime expiresAt;
  final DateTime cooldownUntil;

  factory SmsOtpRequestResult.fromJson(Map<String, dynamic> json) {
    final requestId = json['request_id'];
    final expires = json['expires_at'];
    final cooldown = json['cooldown_until'];
    final expiresAt = expires is String ? DateTime.tryParse(expires)?.toUtc() : null;
    final cooldownUntil = cooldown is String ? DateTime.tryParse(cooldown)?.toUtc() : null;
    if (requestId is! String || requestId.trim().isEmpty || expiresAt == null || cooldownUntil == null) {
      throw const FormatException('invalid SMS OTP response');
    }
    return SmsOtpRequestResult(
      requestId: requestId,
      expiresAt: expiresAt,
      cooldownUntil: cooldownUntil,
    );
  }
}

abstract interface class SmsOtpGateway {
  Future<SmsOtpRequestResult> requestSmsOtp({required String phone});
  Future<void> verifySmsOtp({required String requestId, required String code});
  Future<void> cancel() async {}
}

String _smsOtpMessage(Object error) {
  final code = error.toString();
  if (code.contains('AUTH_SMS_OTP_INVALID')) return '验证码不正确，请重新输入。';
  if (code.contains('AUTH_SMS_OTP_EXPIRED')) return '验证码已过期，请重新获取。';
  if (code.contains('AUTH_SMS_OTP_TOO_MANY_ATTEMPTS')) return '尝试次数过多，请稍后再试。';
  if (code.contains('AUTH_SMS_OTP_RATE_LIMITED') || code.contains('AUTH_RATE_LIMITED')) {
    return '操作较频繁，请稍后再试。';
  }
  if (code.contains('AUTH_SMS_OTP_COOLDOWN')) return '验证码已发送，请稍后再试。';
  if (code.contains('AUTH_ACCOUNT_UNAVAILABLE')) return '当前账号暂时无法登录。';
  if (code.contains('UNAVAILABLE')) return '手机号验证码暂不可用，请使用邮箱登录。';
  return '暂时无法完成手机号登录，请稍后再试。';
}

class SmsOtpPage extends StatefulWidget {
  const SmsOtpPage({
    super.key,
    required this.gateway,
    required this.privacyConsentGranted,
    required this.onAuthenticated,
    this.onCancel,
  });

  final SmsOtpGateway gateway;
  final bool privacyConsentGranted;
  final VoidCallback onAuthenticated;
  final VoidCallback? onCancel;

  @override
  State<SmsOtpPage> createState() => _SmsOtpPageState();
}

class _SmsOtpPageState extends State<SmsOtpPage> {
  final phoneController = TextEditingController();
  final codeController = TextEditingController();
  Timer? _cooldownTimer;
  DateTime? _cooldownUntil;
  String? _requestId;
  String? _error;
  String? _message;
  bool _requesting = false;
  bool _verifying = false;
  bool _cancelled = false;
  int _generation = 0;

  bool get _privacyGranted => widget.privacyConsentGranted && !_cancelled;
  bool get _coolingDown => _cooldownUntil != null && _cooldownUntil!.isAfter(DateTime.now().toUtc());
  bool get _busy => _requesting || _verifying;

  @override
  void dispose() {
    _generation += 1;
    _cooldownTimer?.cancel();
    phoneController.dispose();
    codeController.dispose();
    super.dispose();
  }

  Future<void> _requestCode() async {
    if (!_privacyGranted || _busy || _coolingDown || phoneController.text.trim().isEmpty) return;
    final generation = ++_generation;
    setState(() { _requesting = true; _error = null; _message = null; });
    try {
      final result = await widget.gateway.requestSmsOtp(phone: phoneController.text.trim());
      if (!mounted || generation != _generation || !_privacyGranted) return;
      setState(() {
        _requestId = result.requestId;
        _cooldownUntil = result.cooldownUntil;
        _requesting = false;
        _message = '验证码已发送。';
      });
      _startCooldownTimer();
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() { _requesting = false; _error = _smsOtpMessage(error); });
    }
  }

  void _startCooldownTimer() {
    _cooldownTimer?.cancel();
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || !_coolingDown) {
        _cooldownTimer?.cancel();
        setState(() {});
      } else {
        setState(() {});
      }
    });
  }

  Future<void> _verify() async {
    final requestId = _requestId;
    final code = codeController.text.trim();
    if (!_privacyGranted || _busy || requestId == null || code.length != 6) return;
    final generation = ++_generation;
    setState(() { _verifying = true; _error = null; });
    try {
      await widget.gateway.verifySmsOtp(requestId: requestId, code: code);
      if (!mounted || generation != _generation || !_privacyGranted) return;
      codeController.clear();
      widget.onAuthenticated();
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() { _verifying = false; _error = _smsOtpMessage(error); });
    }
  }

  Future<void> _cancel() async {
    if (_cancelled) return;
    _cancelled = true;
    ++_generation;
    _cooldownTimer?.cancel();
    codeController.clear();
    if (mounted) setState(() {});
    await widget.gateway.cancel();
    if (mounted) widget.onCancel?.call();
  }

  @override
  Widget build(BuildContext context) {
    final canRequest = _privacyGranted && !_busy && !_coolingDown && phoneController.text.trim().isNotEmpty;
    return PopScope<void>(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) unawaited(_cancel());
      },
      child: Scaffold(
        backgroundColor: JiYiTodayVisuals.background,
        appBar: AppBar(
          title: const Text('手机号验证码登录'),
          backgroundColor: JiYiTodayVisuals.background,
          foregroundColor: JiYiTodayVisuals.navy,
          elevation: 0,
          leading: IconButton(icon: const Icon(Icons.close), onPressed: _cancel),
        ),
        body: ListView(
        padding: const EdgeInsets.fromLTRB(24, 28, 24, 32),
        children: [
          const Text('用手机号登录', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: JiYiTodayVisuals.navy)),
          const SizedBox(height: 10),
          const Text('验证码只用于本次登录，不会保存在设备上。', style: TextStyle(color: JiYiTodayVisuals.secondaryText)),
          const SizedBox(height: 28),
          TextField(
            controller: phoneController,
            keyboardType: TextInputType.phone,
            enabled: !_busy && _privacyGranted,
            decoration: const InputDecoration(labelText: '手机号', hintText: '+8613812345678'),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: canRequest ? _requestCode : null,
            child: Text(_requesting ? '正在发送…' : _coolingDown ? '请稍候' : '获取验证码'),
          ),
          if (_requestId != null) ...[
            const SizedBox(height: 18),
            TextField(
              controller: codeController,
              keyboardType: TextInputType.number,
              maxLength: 6,
              enabled: !_busy && _privacyGranted,
              decoration: const InputDecoration(labelText: '验证码'),
              onChanged: (_) => setState(() {}),
            ),
            FilledButton(
              onPressed: _verifying || !_privacyGranted || codeController.text.trim().length != 6 ? null : _verify,
              child: Text(_verifying ? '正在验证…' : '登录'),
            ),
          ],
          if (_message != null) ...[
            const SizedBox(height: 16),
            Text(_message!, style: const TextStyle(color: JiYiTodayVisuals.secondaryText)),
          ],
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
          ],
          const SizedBox(height: 24),
          AuthV3Agreement(
            accepted: widget.privacyConsentGranted && !_cancelled,
            onChanged: (accepted) {
              if (!accepted) {
                unawaited(_cancel());
              }
            },
          ),
        ],
        ),
      ),
    );
  }
}
