# JiYi Auth UX V3 Specification

Status: DESIGN AUTHORITY + SPEC ONLY

This document defines the approved direction for JiYi Auth UX V3. It does not authorize Flutter, backend, native, provider, or identity implementation in this phase.

## 1. Design Authority

Master Design Authority:

- `mobile/design_reference/v3/auth/auth_flow_board.png`
- Source: user-provided original board
- Source dimensions: `1536 × 1024` RGB PNG
- The board is preserved byte-for-byte. It contains five phone states and their explanatory captions.

The board is the visual authority for the Auth V3 direction. Existing email-login UI is current implementation evidence only; it is not the visual authority.

Auth V3 inherits the same brand language already approved for Today V3: warm dawn landscape, warm off-white surfaces, deep navy text, JiYi blue primary action, generous white space, large radii, and restrained shadows.

## 2. Product Goals

The final consumer authentication hierarchy is:

1. Primary: phone one-tap login supplied by the real carrier/provider
2. Primary: WeChat login
3. Fallback: phone number + SMS OTP
4. Backup: email login

All providers must resolve to one canonical `JiYi user_id`. A phone identity, WeChat identity, and email identity are provider identities, not separate consumer accounts.

The product must feel like a consumer memory app, not an enterprise SaaS credential form. The first screen should lead with trust, recognition, and a simple next action; email/password fields must not occupy the whole first screen.

Capability rule:

- `AVAILABLE`: may be rendered as an enabled action and may call a real provider.
- `PLANNED` or `DISABLED`: must be hidden from current release UI unless the provider is genuinely integrated and capability-gated.
- A visible fake action followed by “暂未开放” is prohibited.

## 3. Authentication State Model

| State | Meaning | UI contract |
| --- | --- | --- |
| `SIGNED_OUT` | No valid authenticated authority is available | Show capability-driven Auth shell; show only real available providers |
| `SILENT_SESSION_RECOVERY` | Durable session exists and the app is refreshing authority | Keep the persistent shell when possible; do not show a login page or full-screen login spinner for a recoverable refresh |
| `PHONE_ONE_TAP_AVAILABLE` | Real carrier one-tap capability is available | Show the one-tap entry and confirmation state |
| `PHONE_ONE_TAP_UNAVAILABLE` | Carrier/provider cannot provide a phone identity now | Show consumer copy “暂时无法获取本机号码” and real fallbacks |
| `SMS_OTP` | Real SMS provider is available and the user is using phone fallback | Show phone, OTP, resend, and verification states |
| `WECHAT` | Real WeChat provider is available and the user is authorizing | Show WeChat authorization, cancellation, and failure states |
| `EMAIL` | Existing email provider flow | Show email/password, verification, reset, and registration states |
| `AUTHENTICATING` | A provider request or email operation is in flight | Disable only the relevant action and preserve the shell; this does not require a full-screen loading page |
| `AUTH_ERROR` | A provider or protocol operation failed | Show consumer-safe error copy and the valid recovery action; never expose SDK/provider/network internals |

`AUTHENTICATING` is a control-flow state, not a mandate to replace the whole screen with a spinner.

## 4. Screen Inventory

### 01 Main Login

Purpose: establish JiYi identity and offer the highest-confidence consumer entry points.

- Primary CTA: `本机号码一键登录`
- Secondary primary action: `微信登录`
- Alternative section: `手机号验证码登录`, `邮箱登录`
- Agreement footer: `登录即表示同意《用户协议》与《隐私政策》`
- Current release behavior: only render the entries whose provider capability is `AVAILABLE`; with current capabilities, the real email path is the only enabled provider.

### 02 One-Tap Confirmation

Purpose: let the user confirm the real operator-provided masked number before establishing the canonical account session.

- Display a real masked number, for example `138 **** 8888`.
- Primary CTA: `一键登录`
- Fallback: `使用其他手机号登录`
- The number must come from the carrier/provider response. Production must never synthesize a phone number for visual completeness.

### 03 SMS OTP Login

Purpose: provide the phone fallback when one-tap is unavailable or the user chooses another number.

- Phone field with `+86` selector and phone input
- `获取验证码` action
- OTP field
- Resend action with countdown, for example `重新发送 (60s)`
- `登录` action
- Backup link: `使用邮箱登录`
- Current release behavior: hidden until a real SMS provider is integrated.

### 04 Email Login

Purpose: preserve the currently implemented real authentication provider as a backup path.

- Email input
- Password input or the exact credential shape supported by the current provider
- `登录`
- `忘记密码？`
- Registration entry
- Email verification and password reset remain reachable through the current real flow.

### 05 One-Tap Unavailable

Purpose: explain a provider capability problem without exposing implementation details and offer real alternatives.

- Consumer message: `暂时无法获取本机号码`
- Supporting copy: `可能是当前网络或运营商服务不可用，你可以使用其他方式登录`
- Fallbacks: SMS OTP, WeChat, and email, each shown only when genuinely available.
- Never display SDK error, carrier token, network stack, provider exception, or raw error code.

## 5. Geometry

Primary review viewport: `390 × 844`, DPR 1.0.

Common geometry, estimated from the board and aligned with Today V3:

- Status bar/system chrome: top approximately `44 px`; home-indicator region approximately `22 px` at the bottom.
- Safe content band: approximately `y=44..822`.
- Horizontal page padding: `20 px` nominal; use `24 px` for primary action/card edges when the board shows the larger inset.
- Large radius: `24 px` for full-width hero/card surfaces; `16 px` for inputs and secondary action surfaces; `999 px` for pills.
- Primary CTA height: `56 px`; secondary action height: `56 px`; minimum interactive target: `48 px`.
- Hero is full-bleed behind the safe content top. The auth composition may use a shorter visible landscape band than Today, but must preserve the left text-safe region.

Screen anchors are design estimates, not implementation permission:

| Screen | Hero / top composition | Main content | Lower actions / agreement |
| --- | --- | --- | --- |
| 01 Main Login | Full-bleed dawn hero; logo/value proposition centered in the upper half | Primary CTA begins around `y≈440`; width `342 px` at `x=24` | WeChat around `y≈538`; alternatives begin around `y≈635`; agreement above home-indicator region |
| 02 One-Tap Confirmation | Back affordance `x≈24, y≈62`; landscape fades into white content around `y≈300` | Icon/heading block centered around `y≈340..470`; masked-number surface width `342 px` | One-tap CTA `h≈56`; fallback link below; content remains above `y≈822` |
| 03 SMS OTP | Back affordance; landscape-to-white transition around `y≈300` | Heading/body around `y≈335..405`; phone field `h≈56`; OTP row `h≈56` | Resend and login actions preserve `48..56 px` targets; email fallback below |
| 04 Email | Same brand hero language, with back affordance | Heading/body around `y≈335..405`; email and password fields each `h≈56` | Login CTA `h≈56`; forgot-password and registration links below |
| 05 One-Tap Unavailable | Same dawn hero; no new visual language | Centered unavailable icon/message around `y≈350..510` | Enabled provider fallbacks are stacked `h≈56`; agreement remains bottom anchored |

The board is the authority for relative hierarchy and composition. Exact implementation values must be measured against the normalized board and then reviewed with overlay/diff; they must not be inferred from the current email page.

## 6. Typography

| Role | Target | Weight | Line height | Color | Alignment | Max lines |
| --- | ---: | --- | ---: | --- | --- | ---: |
| Brand / `迹忆` | `44–52 px` | 700–800 | `1.05` | deep navy | centered on main login | 1 |
| Main headline | `24–28 px` | 700–800 | `1.2` | deep navy | centered or leading by screen | 2 |
| Value proposition | `17–20 px` | 500–600 | `1.45` | deep navy / muted navy | centered on main login | 2 |
| Screen body | `15–16 px` | 400–500 | `1.45` | muted blue-gray | leading | 2–3 |
| Primary button | `16–17 px` | 700 | `1.2` | white on JiYi blue | centered | 1 |
| Secondary login action | `16–17 px` | 600–700 | `1.2` | deep navy; WeChat action uses restrained green icon/accent | centered/leading | 1 |
| Agreement | `11–12 px` | 400–500 | `1.35` | muted blue-gray; links JiYi blue | centered | 2 |
| Error / unavailable text | `14–16 px` | 500–600 | `1.4` | consumer-safe navy/red-orange semantic color | centered or leading | 3 |

Typography must remain legible at larger text scale. Copy may wrap; geometry must not rely on clipping or hidden overflow.

## 7. Color / Surface

These are JiYi V3 semantic roles; values are targets and may be refined only through approved visual review:

- Warm off-white page background: `#FAF8F3`
- Near-white auth surfaces: `#FEFDFE`
- Deep navy text: `#102A50`
- JiYi primary blue: `#2378E8`
- Muted blue-gray text: `#6D829F`
- WeChat green: approximately `#07B65A`, used only as a restrained provider identity cue
- Error / unavailable accent: warm red-orange with sufficient contrast, never raw provider colors
- Border: very light warm/blue-gray, only when needed for input affordance
- Shadow: extremely light, low-opacity navy; never use gray surface as the primary depth cue

The auth surface should remain clearly brighter than the warm off-white page without creating a harsh pure-white block. Provider colors must not overpower JiYi blue.

## 8. Hero Treatment

Candidate asset:

- `mobile/assets/brand/today_hero_default.png`

Reuse is allowed as a brand-language candidate because it contains the approved warm dawn lake/mountain atmosphere and an intentionally quiet left region. Reuse is not an assumption that the final Auth crop must be identical to Today.

Recommended future treatment:

- `BoxFit.cover` within a bounded auth hero layer.
- Keep the left side low-contrast and text-safe.
- Keep the mountain/sun focal area toward the right.
- Use a soft bottom fade into the near-white auth surface if the form begins over the image boundary.
- Do not bake logo, CTA, status bar, form fields, or user data into the image.
- If an auth-specific crop is later approved, it must remain a separate reviewed composition; it must not mutate the approved Today asset.

The current lightweight fallback in `TodayHeroBackground` is not an Auth production design. Auth implementation must define its own failure fallback while preserving the shell and avoiding full-page loading.

## 9. Current Capability Mapping

| Provider | Current Status | UI Behavior Now | Future Behavior |
| --- | --- | --- | --- |
| `EMAIL` | `AVAILABLE` | Keep the existing real email login, registration, verification, reset, and logout behavior; expose it as the current enabled path, visually restyled later | Backup provider under the Auth V3 shell |
| `PHONE_ONE_TAP` | `PLANNED` | Hide from current production UI; no fake CTA | Primary consumer entry after real carrier capability and server exchange exist |
| `SMS_OTP` | `PLANNED` | Hide from current production UI; no fake CTA | Phone fallback with real SMS send, verify, resend, rate limit, and recovery states |
| `WECHAT` | `PLANNED` | Hide from current production UI; no fake CTA | Primary consumer entry after real WeChat authorization and server identity exchange exist |

The Design Authority can show all five states even while current production exposes only the real email capability. Capability-driven visibility is mandatory.

## 10. Account Identity Model

`JiYi user_id` is the canonical account identity and must be issued/confirmed by the server.

Provider identities are attached identities:

- `phone identity`
- `wechat identity`
- `email identity`

Required future rules:

1. Successful provider login resolves to an existing canonical `user_id` or creates exactly one canonical account through the server.
2. A provider identity already attached to another account must not silently create a duplicate account.
3. Binding an identity requires authenticated authority, explicit user confirmation where risk is material, and a server-side conflict result.
4. Account merge must be an explicit, audited server operation with ownership, data-retention, and rollback rules; the client must never merge accounts locally.
5. The client must treat provider subject IDs/tokens as credentials or identity references, never as the canonical user ID.

Current risk: the current email path already receives a server `user_id`, but there is no inspected phone/WeChat identity-binding surface or merge contract. Future provider work must define these before enabling multiple providers in release UI.

## 11. Silent Session Recovery

### A. Valid session

- Read secure durable session material.
- Refresh/revalidate authority as needed.
- Enter Consumer Shell / Today directly.
- Do not show the login page.

### B. Access token expired, refresh session valid

- Refresh in the background.
- Keep the shell visible and preserve the last trusted UI state.
- Do not show a full-screen “正在登录” page.

### C. Temporary Wi-Fi/5G or transport failure

- Preserve durable refresh material.
- Keep the current shell/session state when it was already authenticated.
- Retry on lifecycle/resume or the next bounded authority attempt.
- Do not log the user out merely because the network is briefly unavailable.

### D. Refresh authority terminally invalid

- Clear local session authority only after a terminal server result.
- Stop authenticated-only work fail-closed.
- Enter Auth shell with consumer copy such as `之前的登录状态已经失效，请重新登录。`

Current target principle: `Persistent Shell + stale-while-revalidate`.

Current implementation assessment: partial. The existing code has secure durable refresh material, generation/session fencing, terminal-vs-transient error handling, refresh de-duplication, lifecycle refresh, and server-authoritative `user_id`. However, cold start currently renders a full-screen restore spinner while `restoringSession` is true; a transient cold-start restore failure ends in the unauthenticated Auth page with a message instead of preserving a previously trusted shell. Auth V3 implementation must harden this boundary without weakening terminal invalidation.

## 12. Error / Fallback UX

| Situation | Consumer copy direction | Prohibited output |
| --- | --- | --- |
| One-tap unavailable | `暂时无法获取本机号码` / `你可以使用其他方式登录` | SDK error, carrier token, provider exception |
| SMS send failure | `验证码暂时没有发送成功，请稍后重试。` | HTTP code, SMS vendor name, raw stack |
| SMS expired/invalid | `验证码已失效，请重新获取。` | Provider error enum |
| WeChat cancelled | `你已取消微信登录，可以选择其他方式继续。` | Native cancellation exception |
| WeChat failure | `微信登录暂时不可用，请稍后重试或使用其他方式。` | WeChat SDK diagnostics |
| Email authentication failure | `邮箱或密码不正确。` / current safe mapped copy | Raw server message or credential detail |
| No network | `暂时无法连接，请检查网络后重试。` | Socket/HTTP stack |
| Service unavailable | `服务暂时不可用，请稍后再试。` | Backend exception, trace ID as user copy |

Errors must preserve the Auth shell, retain user-entered safe form data where appropriate, and offer a real next action.

## 13. Agreement / Privacy

The main login and any provider consent boundary must expose:

- `用户协议`
- `隐私政策`
- Phone carrier authorization explanation before one-tap identity exchange
- WeChat authorization explanation before provider handoff

This phase defines UX placement and consent sequencing only. Legal copy, consent storage, and provider SDK implementation are out of scope.

## 14. Existing Code Mapping

| V3 Element | Current File / Symbol | Reusable Logic | Visual Replace | Missing Capability |
| --- | --- | --- | --- | --- |
| Auth shell entry/routing | `mobile/lib/stage1_app.dart` — `JiYiApp`, `_JiYiAppState.build` | Conditional authenticated vs unauthenticated shell, restore flags, logout callback | Replace current full-screen email-first Auth composition with capability-driven Auth shell | Provider capability registry and Auth V3 state router |
| Current email login | `mobile/lib/stage1_app.dart` — `AuthPage`, `_AuthPageState._submitCredentials` | Validation, loading/error handling, safe consumer copy, callback to authenticated shell | Replace visual layout; retain provider behavior | None for current email login |
| Email registration/verification | `AuthPage._submitCredentials`, `_verifyEmail`, `_resendVerification` | Real register, verify, resend, delivery-pending behavior | Restyle as backup flow under V3 | None for current provider; future shell routing |
| Password reset | `AuthPage._requestReset`, `_resetPassword` | Request/reset flow and safe messages | Restyle and place behind email backup | None for current provider |
| Session persistence | `mobile/lib/auth_session_store.dart` — `PersistedAuthSession`, `SecureAuthSessionStore`, `MemoryAuthSessionStore` | Secure refresh/session persistence, malformed-state fail-closed behavior, installation ID | No visual replacement; keep behind new shell | Provider identity binding is absent |
| Server login/session establishment | `mobile/lib/api_client.dart` — `login`, `_establishAuthenticatedSession` | Server-issued access token, refresh token, session ID, access expiry, canonical `user_id` | No visual replacement | Phone/WeChat/SMS endpoints and identity exchange |
| Cold-start recovery | `mobile/lib/api_client.dart` — `restorePersistedSession`; `mobile/lib/stage1_app.dart` — `_restoreServerSession` | Refresh rotation, terminal/transient distinction, profile fetch, authenticated shell routing | Replace full-screen restore treatment with persistent-shell stale-while-revalidate behavior | Shell-preserving recovery state |
| Background refresh | `api_client.dart` — `refreshCurrentSession`, `ensureFreshServerAuthority`; `stage1_app.dart` — `_refreshServerAuthority` | In-flight refresh de-duplication, session generation fencing, lifecycle/timer refresh | No visual replacement except non-blocking status treatment if needed | Auth V3 recovery coordinator/capability state |
| Logout | `api_client.dart` — `logout`, `logoutAll`; `stage1_app.dart` — `_logout` | Local authority invalidation before/around server revoke, shell reset | Restyle destination Auth shell | Identity unlink/merge policy |
| Consumer shell | `stage1_app.dart` — `AppShell` | Existing authenticated Today/consumer navigation | Keep shell; Auth must enter it without a login detour when authority is valid | None for shell entry |
| Phone one-tap | No current provider symbol | None | New V3 screen family only after provider integration | Carrier SDK/server exchange, masked-number authority, failure states |
| SMS OTP | No current provider symbol | Existing installation ID/session establishment may be reusable | New V3 fallback screen family | Send/verify/resend/rate-limit provider and API |
| WeChat | No current provider symbol | Canonical session establishment pattern may be reusable | New V3 provider entry and consent flow | WeChat SDK/server exchange/cancel states |

## 15. Implementation Phases

No phase is implemented in this spec-only task.

1. `AUTH-UI-01` — V3 shell and email current provider: build capability-driven shell, visual authority layout, and preserve real email logic.
2. `AUTH-01` — Canonical Auth Identity foundation: server-side provider identity model, user ID resolution, conflict contract, audit events.
3. `AUTH-02` — Phone One-Tap: real carrier capability, masked-number confirmation, server exchange, unavailable state.
4. `AUTH-03` — SMS OTP fallback: send/verify/resend/rate limits, recovery and abuse controls.
5. `AUTH-04` — WeChat Login: real authorization, cancellation/error handling, identity resolution.
6. `AUTH-05` — Identity Binding / Merge: explicit binding, conflict confirmation, audited server merge policy.
7. `AUTH-06` — Silent Session Recovery hardening: persistent shell, stale-while-revalidate, bounded retry, terminal invalidation.

## 16. Visual Acceptance

For each approved Auth state:

`Reference → Spec → Actual → Overlay → Diff → Human Approval`

Acceptance must cover:

- `390 × 844`, DPR 1.0, zh-CN, approved font/runtime authority
- system status bar and home-indicator treatment
- hero crop and left text-safe region
- brand/value proposition hierarchy
- enabled-provider visibility and disabled-provider absence
- CTA size, radius, color, and readable contrast
- agreement/privacy placement
- loading/error/fallback shell persistence
- no fake phone, WeChat, SMS, or provider data

Golden images, when later authorized, are regression baselines only. The Design Authority remains `auth_flow_board.png` and human approval remains required.
