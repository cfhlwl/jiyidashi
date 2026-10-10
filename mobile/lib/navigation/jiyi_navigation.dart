import 'package:flutter/material.dart';

/// Compatibility contract for the authenticated five-tab shell.
///
/// The enum contains presentation/navigation metadata only. Session, API, and
/// owner authority remain in AppShell and the feature pages.
enum JiYiDestination { today, memory, life, family, profile }

extension JiYiDestinationMetadata on JiYiDestination {
  int get index {
    switch (this) {
      case JiYiDestination.today:
        return 0;
      case JiYiDestination.memory:
        return 1;
      case JiYiDestination.life:
        return 2;
      case JiYiDestination.family:
        return 3;
      case JiYiDestination.profile:
        return 4;
    }
  }

  String get label {
    switch (this) {
      case JiYiDestination.today:
        return '今天';
      case JiYiDestination.memory:
        return '记忆';
      case JiYiDestination.life:
        return '人生';
      case JiYiDestination.family:
        return '家庭';
      case JiYiDestination.profile:
        return '我的';
    }
  }

  IconData get icon {
    switch (this) {
      case JiYiDestination.today:
        return Icons.home_outlined;
      case JiYiDestination.memory:
        return Icons.photo_library_outlined;
      case JiYiDestination.life:
        return Icons.menu_book_outlined;
      case JiYiDestination.family:
        return Icons.people_outline;
      case JiYiDestination.profile:
        return Icons.person_outline;
    }
  }

  IconData get selectedIcon {
    switch (this) {
      case JiYiDestination.today:
        return Icons.home;
      case JiYiDestination.memory:
        return Icons.photo_library;
      case JiYiDestination.life:
        return Icons.menu_book;
      case JiYiDestination.family:
        return Icons.people;
      case JiYiDestination.profile:
        return Icons.person;
    }
  }
}

class JiYiDestinationDescriptor {
  const JiYiDestinationDescriptor({required this.destination});

  final JiYiDestination destination;

  int get index => destination.index;
  String get label => destination.label;
  IconData get icon => destination.icon;
  IconData get selectedIcon => destination.selectedIcon;
}

typedef JiYiDestinationPageFactory = Widget Function(
  JiYiDestination destination,
);

/// The small typed bridge between stable integer callers and page factories.
abstract final class JiYiDestinationCatalog {
  static const descriptors = <JiYiDestinationDescriptor>[
    JiYiDestinationDescriptor(destination: JiYiDestination.today),
    JiYiDestinationDescriptor(destination: JiYiDestination.memory),
    JiYiDestinationDescriptor(destination: JiYiDestination.life),
    JiYiDestinationDescriptor(destination: JiYiDestination.family),
    JiYiDestinationDescriptor(destination: JiYiDestination.profile),
  ];

  static bool isValidIndex(int index) => index >= 0 && index < descriptors.length;

  static bool isSelected(
    JiYiDestination destination,
    int selectedIndex,
  ) =>
      destination.index == selectedIndex;

  static JiYiDestination fromIndex(int index) {
    if (!isValidIndex(index)) {
      throw RangeError.index(index, descriptors, 'index');
    }
    return descriptors[index].destination;
  }

  static List<Widget> buildPages(JiYiDestinationPageFactory factory) {
    return [
      for (final descriptor in descriptors) factory(descriptor.destination),
    ];
  }
}

/// The current V2 hub is intentionally retained as a secondary People + Life
/// route until those surfaces receive their own visual migration batches.
abstract final class JiYiSecondaryRoutePolicy {
  static const retainV2Home = true;
}

abstract final class JiYiShellPolicy {
  static bool showBottomNavigation({
    required bool onboardingActive,
    required bool accountDeletionActive,
  }) {
    return !onboardingActive && !accountDeletionActive;
  }
}

/// Minimal route construction seam. It keeps the current Material transition
/// and Navigator authority while giving detail routes one place to evolve.
abstract final class JiYiNavigator {
  static MaterialPageRoute<T> page<T>({
    required WidgetBuilder builder,
    RouteSettings? settings,
  }) {
    return MaterialPageRoute<T>(builder: builder, settings: settings);
  }

  static MaterialPageRoute<T> detail<T>({
    required WidgetBuilder builder,
    RouteSettings? settings,
  }) {
    return page<T>(builder: builder, settings: settings);
  }

  static Future<T?> push<T>(
    BuildContext context, {
    required WidgetBuilder builder,
    RouteSettings? settings,
  }) {
    return Navigator.of(context).push<T>(
      page<T>(builder: builder, settings: settings),
    );
  }

  static Future<T?> pushDetail<T>(
    BuildContext context, {
    required WidgetBuilder builder,
    RouteSettings? settings,
  }) {
    return Navigator.of(context).push<T>(
      detail<T>(builder: builder, settings: settings),
    );
  }
}
