# SEC-014: Sensitive Operation Confirmation Standard V1

## 1. Security boundary

Second-confirm is a **presentation and intent boundary**, never authorization.

Every mutation that uses this standard follows:

```text
explicit user intent
→ second-confirm
→ fresh session / resource / authority revalidation
→ canonical server or OS authorization
→ mutation
→ terminal response
```

A stale dialog cannot grant permission, widen scope, bypass membership/ownership, replace privacy state, or replace OS permission.

## 2. V1 inventory

| Operation | Strength | Flutter | Mini | Confirmation |
| --- | --- | --- | --- | --- |
| Personal data export | disclosure | no current product entrypoint | no current product entrypoint | standard copy is defined for future wiring; no new capability added |
| SEC-007 bulk data delete | destructive data | no current product entrypoint | no current product entrypoint | standard copy is defined for future wiring; no new capability added |
| Account delete | irreversible account | existing flow | no current product entrypoint | typed phrase + explicit irreversible action |
| Family grant | permission mutation | existing | existing | explicit allow + affected scope |
| Family revoke | permission mutation | existing | existing | explicit revoke + affected scope |
| Family member remove / leave | permission mutation | not currently exposed in Flutter V2 | existing | explicit relationship/grant cleanup |
| Automatic location start / permission escalation | sensitive location | existing | not currently exposed | explicit start + fresh privacy authority before native action |
| Emergency location start | sensitive location | not currently exposed in Flutter V2 | existing | explicit recipient + duration + current-location scope |
| Stop/revoke location sharing | safe-off privacy action | existing automatic location stop | existing emergency revoke | remains immediately available; no extra friction is added to stop disclosure |

The absence of a client entrypoint is intentional: SEC-014 does not invent export, bulk-delete, account-delete, location, family, or emergency capabilities on a client that does not already own them.

## 3. Product contract

Every confirmation states what happens, the affected scope, whether it can be undone, who gains or loses access when relevant, and an explicit action label. Internal enum values and backend error codes are not user copy.

Flutter and Mini share the same semantic fields: `strength / title / summary / scope / undo / confirm action`. Flutter account delete retains its stronger typed-phrase gate.

## 4. Stale-state and session handling

### Account delete

Flutter preserves PREPARE → LOCAL PURGE → COMMIT and request-id idempotency. Each HTTP request is bound to the authenticated session snapshot, so an account/session switch rejects late results.

### Family grants

Family permission replacement is a complete replacement API. The client must never build the PUT body from the grant matrix that originally rendered the switch.

```text
open confirmation
→ confirm
→ verify same auth session
→ GET current family
→ GET current grants
→ verify target still exists
→ derive requested toggle from fresh grant
→ PUT complete replacement
→ verify session is still current
→ publish canonical response
```

If the requested state is already canonical, the client treats it as completed and sends no redundant mutation.

### Sensitive location

Flutter automatic-location start and permission escalation use the shared second-confirm. After confirm, AppShell re-reads server privacy authority and native location status before enable/start/settings. OS permission remains independently authoritative.

Mini emergency sharing re-reads current family and authenticated profile after confirm before creating the share. Emergency revoke is a privacy safe-off path: it first refreshes canonical share state, then revokes if still active; already-stopped state converges without a duplicate mutation.

## 5. Cancel, double-submit and late response

- cancel / back / dismiss performs no mutation;
- callers enter single-flight before opening confirmation;
- account delete reuses one destructive request id across ambiguous retries;
- Family mutation responses are ignored after session/page generation invalidation;
- Flutter publication remains guarded by `mounted` and authenticated-session snapshots;
- Mini uses a mutation epoch plus auth owner/epoch for stale result suppression.

## 6. Stable user-facing errors

State/session/resource changes map to:

```text
状态刚刚发生变化，请重新打开后再试
```

Lost authorization maps to:

```text
你现在没有权限执行这个操作
```

Unknown backend codes are never displayed directly. Existing Family-specific safe mappings remain authoritative where more precise.

## 7. Existing authority retained

SEC-014 does not replace or weaken SEC-007 data deletion, SEC-008 account deletion, exact Family membership/grant authorization, emergency-share server authority/expiry, privacy pause lifecycle, or native OS location permission.

No new authentication factor, biometric framework, role model, entitlement, location capability, emergency capability, or audit subsystem is introduced.
