# UIUX-V3-ACCEPTANCE-001 验收报告

> Issue：[#288](https://github.com/cfhlwl/jiyidashi/issues/288)
> 验收分支：`codex/uiux-v3-acceptance-001-20261017`
> 报告状态：AUTO 验收完成；FIELD 验收未开始
> Design Authority PNG：只读，本轮未修改

## 1. Exact source and toolchain

| 项目 | 值 |
| --- | --- |
| `origin/main` at checkout | `88862ea998f593d62ddb2ac18d75c5f9b33663d0` |
| acceptance source `HEAD` | `a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f` |
| merge-base | `88862ea998f593d62ddb2ac18d75c5f9b33663d0` |
| ahead / behind | `3 / 0` |
| Flutter | `3.47.4` |
| Dart | `3.13.3` |
| workspace | `D:/jiyi-v3-acceptance-001` |
| shared AUTH workspace | `D:/jiyi`，未触碰 |

## 2. Automatic acceptance matrix

本矩阵只把已有 exact-head 或本轮实际运行的证据标为 PASS；未执行项目不以代码存在或历史 PR 结果代替证据。

| 模块 | 自动证据 | 状态 | 备注 |
| --- | --- | --- | --- |
| Today V3 | `today_b2_visual_fixture_test.dart`, `today_footprint_page_test.dart` | PASS 功能；视觉 baseline FAIL | `design_authority_today_b2.png` 当前差异 4.90%，不更新基线 |
| Auth UI V3 | `auth_v3_capability_test.dart`, `auth_v3_visual_fixture_test.dart` | PASS 功能；视觉 baseline FAIL | main/email 两张严格旧基线差异，未修改 Golden |
| Batch 4A Place Detail | `place_detail_test.dart` | PASS | privacy/map/owner/API rebind focused tests 通过 |
| Batch 4B People / Person Detail | `batch4b_people_person_detail_test.dart` | PASS | truthful V2 data、mutation fencing、compact/large text 通过 |
| Batch 4C Graph Neighborhood | `batch4c_graph_neighborhood_test.dart` | PASS | strict nodes/edges、empty/truncated、owner rebind 通过 |
| Batch 5A Life Home | `batch5a_life_home_test.dart` | PASS | four real entries、route/back、dark、API rebind 通过 |
| Batch 5B Life Events | `batch5b_life_events_test.dart`, visual test | PASS | list/detail/editor、rebind、mutation path 通过 |
| Batch 5C Life Stages | `batch5c_life_stages_test.dart` | PASS | list/detail/editor、reasoning、dialog fencing 通过 |
| Batch 5D Life History / Memoirs | `batch5d_life_history_memoirs_test.dart` | PASS | timezone grouping、memoir rebind、photo route ownership 通过 |
| Timeline / Memory Detail | `timeline_memory_detail_v3_test.dart` | PASS | truthful data、detail/back、reminder、small screen 通过 |
| Shared V3 semantics | `v3_navigation_contract_test.dart`, `v3_shared_components_test.dart` | PASS | AppShell destinations, selected semantics, tap target contract 通过 |

### Local focused result

Command:

```text
flutter test
  test/today_b2_visual_fixture_test.dart
  test/today_footprint_page_test.dart
  test/auth_v3_visual_fixture_test.dart
  test/auth_v3_capability_test.dart
  test/place_detail_test.dart
  test/batch4b_people_person_detail_test.dart
  test/batch4c_graph_neighborhood_test.dart
  test/batch5a_life_home_test.dart
  test/batch5b_life_events_test.dart
  test/batch5b_life_events_visual_test.dart
  test/batch5c_life_stages_test.dart
  test/batch5d_life_history_memoirs_test.dart
  test/timeline_memory_detail_v3_test.dart
  test/v3_navigation_contract_test.dart
  test/v3_shared_components_test.dart
  --reporter expanded
```

Result: **159 tests executed; 156 passed; 3 failed; 0 new functional failure**.

The three failures are strict visual comparisons only:

- `today_b2_visual_fixture_test.dart: Today B2 deterministic visual fixture` → `design_authority_today_b2.png`, 4.90% diff.
- `auth_v3_visual_fixture_test.dart: Auth V3 fixture 01 main login` → `auth_v3_main_login.png`, 2.67% diff.
- `auth_v3_visual_fixture_test.dart: Auth V3 fixture 04 email` → `auth_v3_email_login.png`, 1.75% diff.

No Golden or Design Authority PNG was changed.

## 3. Gate status

| Gate | Run / exit code | Status |
| --- | --- | --- |
| `flutter analyze` on exact main | exit `0`, `No issues found` | PASS |
| focused V3 functional tests | see above | PASS |
| full Flutter suite | Mobile CI Android job | PASS in hosted Linux CI; local Windows full suite remains platform/baseline-failing |
| `mobile-ci` | run `38997323493` / #1924 | PASS |
| `mobile-visual-preview` | run `38997323331` / #1775 | PASS |
| `backend-ci` | run `38997323339` / #2383 | PASS |
| `miniprogram-ci` | run `38997323364` / #1749 | PASS |
| `ios-unsigned-ipa` | no manual dispatch performed | NOT RUN |
| `core004-ios-trollstore-fix` | no manual dispatch performed | NOT RUN |

Existing workflow note: ordinary `mobile-ci` and visual preview use the repository's fail-closed CI endpoint/configuration gates. The Issue #288 production artifact requirement is stricter: iOS dispatch must use `https://jiyi.ccwl.net.cn/v1`; no `api.example.invalid` result may be reported as real-device acceptance.

## 4. Visual acceptance

The original files under `mobile/design_reference/v3/` remain read-only. Current visual classification is **DERIVED V3 / V3_PARTIAL**, not a claim of 1:1 restoration.

The acceptance run must distinguish:

1. approved/committed Golden baselines;
2. candidate-only screenshots from production widgets;
3. historical visual mismatches;
4. new regressions introduced by this acceptance branch.

Current local evidence shows three pre-existing strict visual mismatches listed above. They are not being absorbed into baselines by this task.

## 5. Artifact and FIELD status

| Artifact / validation | Status | Required evidence |
| --- | --- | --- |
| iOS unsigned release IPA | NOT RUN | requires manual dispatch with real API URL; no IPA or SHA256 sidecar claimed |
| TrollStore installation | NOT RUN | unsigned IPA compatibility is not installation proof |
| Android debug APK | PASS in Mobile CI / Visual Preview build steps | hosted build passed; downloadable APK/SHA256 artifact was not exposed by the connector, so installability is not claimed |
| Android release APK | NOT RUN | standard PR workflows do not provide a real release-signed artifact |
| iOS physical device | NOT RUN | install/login/photo/location/map/life navigation evidence |
| Android physical device | NOT RUN | install/login/photo/location/map/life navigation evidence |
| CORE-004 24h/72h | NOT RUN | separate long-running certification |

No secrets, provider credentials, or production configuration changes are included in this report.

## 6. Findings

| Severity | Finding | State |
| --- | --- | --- |
| P0 | None observed in local focused acceptance | 0 |
| P1 | No new functional P1 observed; required exact-head CI and artifact gates still pending | 0 observed / gate pending |
| P2 | Three existing visual baseline mismatches listed in §2; no baseline update authorized | 3 existing visual findings |

## 7. Exact-head hosted evidence

All four PR-triggered runs above reported checkout SHA `a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f`.

Visual Preview uploaded the following exact-head artifacts (14-day retention):

- `uiux-v3-design-authority-audit-a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f`, artifact `12087892302`, digest `sha256:a77f0a4eb5e9a4e28ad2fb04f3f45b0302f7f3969e7333431f7c57ca4fd57200`
- `flutter-visual-preview-a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f`, artifact `12087447521`, digest `sha256:2eb645e26afd63595063adda2a65218714cf0e83eb3230f9f53ca772178ab58c`
- `memory-v3-candidates-a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f`, artifact `12088035472`, digest `sha256:8bcd0e41b8856bcdfa05efbaf42bad9d0c4115ec3b4f57e16394c29058d0da4a`
- `uiux-v3-batch5d-life-history-memoirs-candidates-a99ad8f9eac25c3f3ddf27a1fd0e8753f5ec707f`, artifact `12087940930`, digest `sha256:400539c1a349b59c73fc1999822dc6bd38bf450a0e85605af07d4c5822af24be`

The visual job executed Analyze, all listed V3 targeted suites, candidate generation, Design Authority audit generation, full committed-Golden testing, and the Android debug build. Its result was PASS. No Golden or Design Authority PNG was modified by this acceptance branch.

## 8. Local full-suite classification

On Windows Flutter 3.47.4, the local full suite ended `+607 ~1 -41`. The failures were existing strict visual/Golden comparisons plus Windows path-separator and photo-import fixture behavior; no production file was changed to absorb them. Hosted exact-head Mobile CI and Visual Preview passed, so the local Windows result is retained as environment/baseline evidence rather than a hosted gate result.

The focused local matrix remains `159 executed / 156 passed / 3 strict visual mismatches`, with no new functional failure. The three mismatches are the Today B2 authority fixture and Auth V3 main/email fixtures listed in §2.

## 9. FIELD and release artifact gate

The following remain explicitly open and cannot be inferred from hosted CI:

- manual `ios-unsigned-ipa` release dispatch with `https://jiyi.ccwl.net.cn/v1`;
- `core004-ios-trollstore-fix` run on the same exact SHA;
- IPA bundle/plist/arm64/SHA256 sidecar verification;
- valid release-signed Android APK and SHA256 verification;
- real iOS TrollStore install, Android physical install, login/media/location/map/life navigation checks;
- CORE-004 24h/72h evidence.

Therefore this PR establishes AUTO hosted acceptance evidence only. Overall status remains **HOLD for release-artifact and FIELD gates**; visual classification remains **DERIVED V3 / V3_PARTIAL**.

No secrets, provider credentials, production configuration, Golden files, or Design Authority PNGs were changed.
