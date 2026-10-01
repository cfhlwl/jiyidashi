# CORE-004 Field Execution Runbook

This runbook executes Issue #190 without weakening its real-device requirement.

## Build lock before each field run

For each Android/iOS run, record:

```text
git HEAD
app version/build number
artifact/install source
device model (non-unique model name only)
OS version
timezone
permission/background state
battery baseline
local + UTC start time
```

Do not record serial/IMEI/ad IDs or precise coordinates.

A fix discovered during field certification gets a separate narrow defect PR. After that fix merges, produce a new exact build and rerun the affected scenario from the beginning. Preserve the failed run.

## Efficient baseline schedule

C1 may use the **first 24 hours of the same continuous 72-hour C2 field run**, provided that the C1 window independently satisfies every C1 rule:

```text
T0
→ healthy baseline + start snapshots
→ do not deliberately open app UI for first 24h
→ T+24h capture server-side/health/Visit evidence = C1
→ continue normal field use without resetting the run
→ T+72h capture continuity/battery/Visit quality evidence = C2
```

Create separate C1 and C2 evidence JSON records even when they refer to the same physical run window. This keeps the scenario assertions independently reviewable.

Do **not** embed C3 into C2. C3's deliberate ~12h network outage materially changes delivery conditions and should remain a separate run for failure attribution.

## C1 — first 24h UI-independent window

Before T0:

- onboarding complete;
- required location/background authority granted;
- Privacy Pause off;
- Recording Health baseline captured;
- server ACK baseline captured;
- app UI is left closed after setup.

During T0 → T+24h:

- do not deliberately foreground the app;
- use the phone normally;
- if stationary for the whole window, record that fact and perform a separate movement segment.

At T+24h, capture:

- server-observed Recording Health;
- server ACK progression;
- DayFootprint/Visit/Place evidence;
- whether a real movement transition occurred;
- confirmation that AppShell foreground activity was not used to create the evidence.

## C2 — continue the same run to 72h

Continue from C1 through T+72h under normal real-world use.

Record natural examples of:

- walking;
- vehicle/transit;
- stationary periods;
- screen-off/background;
- Wi-Fi/cellular transitions;
- charging and non-charging periods.

At the end record:

- Healthy/Degraded/Blocked/Recovering periods;
- known/unknown gap hours;
- max unexplained gap while authority/platform state was healthy;
- queue pressure/backlog events;
- producer-stop observations;
- server ACK continuity;
- Visit continuity;
- OS battery statistics;
- Visit/Place quality observations: correct stationary visit, correct movement transition, duplicate/split, incorrect merge, missed visit, unexpected assignment.

Frozen V1 fail boundary remains in `acceptance.json`. Do not adjust it after seeing the run.

## C3 — independent ~12h offline replay

Start from a healthy baseline.

```text
network healthy
→ capture before snapshot
→ disable network while location authority remains enabled
→ move through real locations for >=12h
→ capture offline/backlog snapshot
→ restore network
→ wait for automatic replay/drain
→ capture after snapshot
```

Evidence must show:

- durable queue retained data while offline;
- expected DEGRADED/backlog health;
- automatic replay after reconnect;
- stable client UUIDs;
- duplicate UUID count = 0;
- queue drained;
- server ACK advanced;
- retained valid evidence appears in DayFootprint/Visits.

## C4 — process termination

Android records **two distinct semantics**:

1. process death/kill where platform policy still permits recovery;
2. explicit Force Stop, documented separately as stopped-state semantics.

Do not claim recovery from Force Stop before user action if the platform blocks it.

iOS likewise distinguishes system/developer termination/suspension from explicit user force-quit behavior. PASS is truthful platform-contract behavior, not impossible keep-alive.

## C5 — reboot

From healthy recording:

```text
capture pre-reboot state
→ reboot device
→ do not immediately open app
→ observe only platform-authorized recovery
→ capture recovery/unknown state
→ capture eventual valid passive evidence when allowed
```

Record observed time-to-recovery, but do not convert one observation into a universal SLA.

## C6 — Privacy Pause

From healthy state:

```text
enable Privacy Pause
→ confirm PAUSED
→ move during pause
→ exercise late queued delivery where practical
→ resume
```

Require server-side proof that paused-interval evidence is rejected/filtered, no fake Visit is formed, forbidden paused evidence is not replayed, and post-resume valid evidence continues.

## C7 — permission / services disruption

Exercise separately where the platform permits:

- location permission revoke/downgrade;
- system location services off/on;
- background permission change.

Capture health + UI CTA before/during/after. Any false green fails.

## C8 / C9 — real historical queries

After field data exists, use a known certification day.

C8:

```text
“我25号去哪了？” or equivalent
→ deterministic date
→ Visit + Place
→ provider_call_count = 0
```

Record false positive, false negative and ordering discrepancy counts against known movement.

C9:

```text
“25号发生了什么？”
→ bounded DayFootprint + trusted Memory/media evidence
→ optional AI summary
```

Every personal claim must trace to evidence. Also test provider unavailable and no-evidence behavior.

## C10 — health truthfulness

Across the above runs, accumulate examples of:

```text
HEALTHY
DEGRADED
PAUSED
BLOCKED
RECOVERING
UNKNOWN
```

For any state not safely/reproducibly observed, record an explicit reason instead of manufacturing it.

Certification fails on any known false-green observation.

## OWNER_SESSION — isolation

On at least one real device:

```text
owner A has pending/visible state
→ logout/account switch
→ owner B login
```

Prove:

- A queue is not published as B;
- late A health cannot repopulate B;
- B receives no A Visit/Place/health;
- old authority is invalidated.

## End-of-run rule

Do not change `CORE-004 🔵` to 🟠 until every mandatory Android+iOS matrix row is no longer FAIL/BLOCKED and every PASS has preserved evidence.

CI green means only **harness valid**. It does not mean **device certified**.
