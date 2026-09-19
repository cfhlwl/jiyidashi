import Flutter
import UIKit
import XCTest
@testable import Runner

class RunnerTests: XCTestCase {
  private let owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

  func testLocationStartRequiresAlwaysPermissionAndMatchingOwner() {
    XCTAssertTrue(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.canStart(
        ownerUserId: owner,
        enabledOwnerUserId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        authorization: .background,
        locationServicesEnabled: true
      )
    )
  }

  func testAlwaysPermissionOnlyFollowsExplicitEnableWithForegroundGrant() {
    XCTAssertFalse(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: false,
        authorization: .foreground
      )
    )
    XCTAssertFalse(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: true,
        authorization: .notDetermined
      )
    )
    XCTAssertTrue(
      NativeLocationPolicy.shouldRequestAlways(
        explicitAutomaticEnable: true,
        authorization: .foreground
      )
    )
  }

  func testPermissionRevocationStopsRunningProducer() {
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true,
        runtime: .running,
        nativeProducerActive: true
      ),
      .stopped
    )
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: false,
        runtime: .running,
        nativeProducerActive: true
      ),
      .stopped
    )
  }

  func testLocationRelaunchMarksPendingButKeepsProducerStoppedUntilPrivacyVerification() {
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: true,
        runtime: .stopped
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .foreground,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
    XCTAssertEqual(
      NativeLocationPolicy.relaunchState(
        enabledOwnerUserId: owner,
        activeOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .paused
      ),
      NativeLocationRelaunchState(
        restorePending: false,
        runtime: .stopped
      )
    )
  }

  func testInactiveNativeProducerCannotRemainRunning() {
    XCTAssertEqual(
      NativeLocationPolicy.reconcileRuntime(
        ownerUserId: owner,
        enabledOwnerUserId: owner,
        authorization: .background,
        locationServicesEnabled: true,
        runtime: .running,
        nativeProducerActive: false
      ),
      .stopped
    )
  }
}
