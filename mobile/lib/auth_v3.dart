import 'package:flutter/material.dart';

import 'phone_one_tap_bridge.dart';
import 'ui/jiyi_tokens.dart';

/// Provider capabilities are the single visibility authority for Auth V3.
/// Production currently enables email only; future providers stay hidden until
/// their real SDK/API capability is supplied by the host.
enum AuthV3Provider { email, phoneOneTap, smsOtp, wechat }

enum AuthV3Screen {
  mainLogin,
  phoneOneTap,
  smsOtp,
  emailLogin,
  oneTapUnavailable,
}

enum AuthCapabilityStatus { available, planned, disabled, unavailable, unsupported }

@immutable
class AuthCapabilities {
  const AuthCapabilities({
    required bool email,
    required bool phoneOneTap,
    required bool smsOtp,
    required bool wechat,
  }) : emailStatus = email
           ? AuthCapabilityStatus.available
           : AuthCapabilityStatus.disabled,
       phoneOneTapStatus = phoneOneTap
           ? AuthCapabilityStatus.available
           : AuthCapabilityStatus.disabled,
       smsOtpStatus = smsOtp
           ? AuthCapabilityStatus.available
           : AuthCapabilityStatus.disabled,
       wechatStatus = wechat
           ? AuthCapabilityStatus.available
           : AuthCapabilityStatus.disabled;

  const AuthCapabilities.statuses({
    this.emailStatus = AuthCapabilityStatus.disabled,
    this.phoneOneTapStatus = AuthCapabilityStatus.disabled,
    this.smsOtpStatus = AuthCapabilityStatus.disabled,
    this.wechatStatus = AuthCapabilityStatus.disabled,
  });

  const AuthCapabilities.emailOnly()
    : this.statuses(emailStatus: AuthCapabilityStatus.available);

  const AuthCapabilities.allEnabled()
    : this.statuses(
        emailStatus: AuthCapabilityStatus.available,
        phoneOneTapStatus: AuthCapabilityStatus.available,
        smsOtpStatus: AuthCapabilityStatus.available,
        wechatStatus: AuthCapabilityStatus.available,
      );

  final AuthCapabilityStatus emailStatus;
  final AuthCapabilityStatus phoneOneTapStatus;
  final AuthCapabilityStatus smsOtpStatus;
  final AuthCapabilityStatus wechatStatus;

  bool get email => emailStatus == AuthCapabilityStatus.available;
  bool get phoneOneTap =>
      phoneOneTapStatus == AuthCapabilityStatus.available;
  bool get smsOtp => smsOtpStatus == AuthCapabilityStatus.available;
  bool get wechat => wechatStatus == AuthCapabilityStatus.available;

  AuthCapabilityStatus status(AuthV3Provider provider) => switch (provider) {
    AuthV3Provider.email => emailStatus,
    AuthV3Provider.phoneOneTap => phoneOneTapStatus,
    AuthV3Provider.smsOtp => smsOtpStatus,
    AuthV3Provider.wechat => wechatStatus,
  };

  bool supports(AuthV3Provider provider) => switch (provider) {
    AuthV3Provider.email => email,
    AuthV3Provider.phoneOneTap => phoneOneTap,
    AuthV3Provider.smsOtp => smsOtp,
    AuthV3Provider.wechat => wechat,
  };

  AuthCapabilities copyWith({
    AuthCapabilityStatus? emailStatus,
    AuthCapabilityStatus? phoneOneTapStatus,
    AuthCapabilityStatus? smsOtpStatus,
    AuthCapabilityStatus? wechatStatus,
  }) => AuthCapabilities.statuses(
    emailStatus: emailStatus ?? this.emailStatus,
    phoneOneTapStatus: phoneOneTapStatus ?? this.phoneOneTapStatus,
    smsOtpStatus: smsOtpStatus ?? this.smsOtpStatus,
    wechatStatus: wechatStatus ?? this.wechatStatus,
  );
}

/// The only Auth V3 provider capability authority. It performs no pre-login
/// work when privacy has not been explicitly accepted.
class AuthCapabilityAuthority {
  const AuthCapabilityAuthority({required this.phoneOneTapBridge});

  final PhoneOneTapBridge phoneOneTapBridge;

  Future<AuthCapabilities> probe({
    required bool privacyConsentGranted,
    AuthCapabilities baseline = const AuthCapabilities.emailOnly(),
  }) async {
    if (!privacyConsentGranted) {
      return baseline.copyWith(
        phoneOneTapStatus: AuthCapabilityStatus.unavailable,
      );
    }

    try {
      var result = await phoneOneTapBridge.initialize(
        privacyConsentGranted: true,
      );
      if (result.isAvailable) {
        result = await phoneOneTapBridge.checkAvailability();
      }
      final phoneStatus = switch (result.state) {
        PhoneOneTapState.available => AuthCapabilityStatus.available,
        PhoneOneTapState.providerError => AuthCapabilityStatus.unavailable,
        PhoneOneTapState.cancelled ||
        PhoneOneTapState.timeout ||
        PhoneOneTapState.unavailable ||
        PhoneOneTapState.tokenAcquired => AuthCapabilityStatus.unavailable,
      };
      return baseline.copyWith(
        emailStatus: AuthCapabilityStatus.available,
        phoneOneTapStatus: phoneStatus,
      );
    } catch (_) {
      return baseline.copyWith(
        phoneOneTapStatus: AuthCapabilityStatus.unavailable,
      );
    }
  }
}

enum AuthSessionVisualState { unknown, refreshing, valid, signedOut }

class AuthV3Hero extends StatelessWidget {
  const AuthV3Hero({super.key, this.height = 320, this.imageProvider});

  final double height;
  final ImageProvider<Object>? imageProvider;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Stack(
        fit: StackFit.expand,
        children: [
          Image(
            image:
                imageProvider ??
                const AssetImage('assets/brand/today_hero_default.png'),
            fit: BoxFit.cover,
            alignment: Alignment.center,
            errorBuilder: (context, error, stackTrace) => const DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: <Color>[Color(0xFFFFF5E7), Color(0xFFDDEBFA)],
                ),
              ),
            ),
          ),
          const DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                stops: <double>[0.52, 1],
                colors: <Color>[Color(0x00FEFDFE), Color(0xFFFEFDFE)],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class AuthV3BrandLockup extends StatelessWidget {
  const AuthV3BrandLockup({super.key, this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color = JiYiTodayVisuals.navy;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Semantics(
          label: '迹忆',
          image: true,
          child: SizedBox(
            width: compact ? 112 : 180,
            height: compact ? 56 : 90,
            child: Image.asset(
              'assets/brand/jiyi_logo_primary.png',
              fit: BoxFit.contain,
              errorBuilder: (context, error, stackTrace) =>
                  const SizedBox.shrink(),
            ),
          ),
        ),
        SizedBox(height: compact ? 6 : 22),
        SizedBox(
          width: compact ? 180 : 220,
          child: Text(
            '记住生活，\n需要时帮你找回来',
            textAlign: TextAlign.center,
            maxLines: 2,
            style: TextStyle(
              color: color,
              fontSize: compact ? 15 : 18,
              fontWeight: FontWeight.w600,
              height: 1.45,
            ),
          ),
        ),
      ],
    );
  }
}

class AuthV3Card extends StatelessWidget {
  const AuthV3Card({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: JiYiTodayVisuals.card,
        borderRadius: BorderRadius.circular(28),
        boxShadow: const <BoxShadow>[
          BoxShadow(
            color: Color(0x0F102A50),
            blurRadius: 18,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 22, 20, 18),
        child: child,
      ),
    );
  }
}

class AuthV3PrimaryAction extends StatelessWidget {
  const AuthV3PrimaryAction({
    super.key,
    required this.label,
    required this.icon,
    this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 58,
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: JiYiTodayVisuals.primaryBlue,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
        ),
        child: Row(
          children: [
            Icon(icon, size: 22),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const Icon(Icons.chevron_right, size: 24),
          ],
        ),
      ),
    );
  }
}

class AuthV3ProviderRow extends StatelessWidget {
  const AuthV3ProviderRow({
    super.key,
    required this.label,
    required this.icon,
    this.iconColor = JiYiTodayVisuals.navy,
    this.leading,
    this.onPressed,
  });

  final String label;
  final IconData icon;
  final Color iconColor;
  final Widget? leading;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 58,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          backgroundColor: JiYiTodayVisuals.card,
          foregroundColor: JiYiTodayVisuals.navy,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          side: const BorderSide(color: Color(0xFFE0E7EF)),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
        ),
        child: Row(
          children: [
            leading ?? Icon(icon, color: iconColor, size: 24),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const Icon(
              Icons.chevron_right,
              color: JiYiTodayVisuals.secondaryText,
              size: 24,
            ),
          ],
        ),
      ),
    );
  }
}

class AuthV3WeChatGlyph extends StatelessWidget {
  const AuthV3WeChatGlyph({super.key});

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      width: 28,
      height: 24,
      child: Stack(
        children: [
          Positioned(
            left: 0,
            bottom: 0,
            child: Icon(
              Icons.chat_bubble_rounded,
              color: Color(0xFF07B65A),
              size: 21,
            ),
          ),
          Positioned(
            right: 0,
            top: 0,
            child: Icon(
              Icons.chat_bubble_rounded,
              color: Color(0xFF18C86A),
              size: 18,
            ),
          ),
        ],
      ),
    );
  }
}

class AuthV3MethodDivider extends StatelessWidget {
  const AuthV3MethodDivider({super.key});

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(child: Divider(color: Color(0xFFDCE4EC))),
        Padding(
          padding: EdgeInsets.symmetric(horizontal: 14),
          child: Text(
            '其他方式',
            style: TextStyle(
              color: JiYiTodayVisuals.secondaryText,
              fontSize: 13,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
        Expanded(child: Divider(color: Color(0xFFDCE4EC))),
      ],
    );
  }
}

class AuthV3Agreement extends StatelessWidget {
  const AuthV3Agreement({
    super.key,
    this.accepted = false,
    this.onChanged,
  });

  final bool accepted;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final muted = JiYiTodayVisuals.secondaryText;
    final link = JiYiTodayVisuals.primaryBlue;
    final base = TextStyle(
      color: muted,
      fontSize: 11,
      height: 1.35,
      fontWeight: FontWeight.w400,
    );
    final linkStyle = base.copyWith(color: link, fontWeight: FontWeight.w600);
    final consent = GestureDetector(
      key: const ValueKey('auth-v3-privacy-consent'),
      onTap: onChanged == null ? null : () => onChanged!(!accepted),
      child: Container(
        width: 17,
        height: 17,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: accepted ? link : null,
          border: Border.all(
            color: accepted ? link : muted,
            width: 1.3,
          ),
        ),
        child: accepted
            ? const Icon(Icons.check, size: 12, color: Colors.white)
            : null,
      ),
    );
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          consent,
          const SizedBox(width: 7),
          Flexible(
            child: Text.rich(
              TextSpan(
                text: '登录即表示同意 ',
                style: base,
                children: [
                  TextSpan(text: '《用户协议》', style: linkStyle),
                  TextSpan(text: ' 与 ', style: base),
                  TextSpan(text: '《隐私政策》', style: linkStyle),
                ],
              ),
              textAlign: TextAlign.center,
              maxLines: 2,
            ),
          ),
        ],
      ),
    );
  }
}

/// A short-lived neutral shell for unknown/refreshing session authority.
/// It deliberately has no spinner and no login copy, so a recoverable cold
/// start cannot flash Auth before the durable session is resolved.
class AuthV3NeutralBootstrap extends StatelessWidget {
  const AuthV3NeutralBootstrap({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: JiYiTodayVisuals.background,
      body: Stack(
        fit: StackFit.expand,
        children: [
          const Align(
            alignment: Alignment.topCenter,
            child: AuthV3Hero(height: 300),
          ),
          Center(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: JiYiTodayVisuals.card.withValues(alpha: 0.92),
                borderRadius: BorderRadius.circular(24),
              ),
              child: const Padding(
                padding: EdgeInsets.symmetric(horizontal: 24, vertical: 18),
                child: AuthV3BrandLockup(compact: true),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
