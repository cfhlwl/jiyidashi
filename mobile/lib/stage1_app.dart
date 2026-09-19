import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'offline_queue.dart';
import 'offline_sync.dart';
import 'unified_capture_section.dart';
import 'ui/jiyi_theme.dart';
import 'ui/jiyi_components.dart';
import 'ui/jiyi_tokens.dart';

class JiYiApp extends StatefulWidget {
  const JiYiApp({super.key, this.api, this.offlineQueue});

  final JiYiApiClient? api;
  final OfflineQueueStore? offlineQueue;

  @override
  State<JiYiApp> createState() => _JiYiAppState();
}

class _JiYiAppState extends State<JiYiApp> {
  late final JiYiApiClient api = widget.api ?? JiYiApiClient();
  // [人工注释][S1-015] App 级共享一个 SQLite queue store；测试可注入独立数据库，生产默认使用系统数据库目录。
  late final OfflineQueueStore offlineQueue =
      widget.offlineQueue ?? OfflineQueueStore();
  late final OfflineSyncCoordinator sync = OfflineSyncCoordinator(
    api: api,
    store: offlineQueue,
  );
  bool authenticated = false;

  @override
  void dispose() {
    // [人工注释][S1-015] 只关闭本组件自己创建的数据库句柄；外部注入 Store 的生命周期由调用方负责。
    if (widget.offlineQueue == null) {
      unawaited(offlineQueue.close());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '迹忆',
      debugShowCheckedModeBanner: false,
      // 生产 Theme 改为单一事实源；G1 参数与原 Theme 完全一致，预期不产生视觉漂移。
      theme: JiYiTheme.light(),
      home: authenticated
          ? AppShell(
              api: api,
              offlineQueue: offlineQueue,
              sync: sync,
              onLogout: () {
                api.logout();
                setState(() => authenticated = false);
              },
            )
          : AuthPage(
              api: api,
              onAuthenticated: () => setState(() => authenticated = true),
            ),
    );
  }
}

class AuthPage extends StatefulWidget {
  const AuthPage({super.key, required this.api, required this.onAuthenticated});

  final JiYiApiClient api;
  final VoidCallback onAuthenticated;

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  final nicknameController = TextEditingController();
  bool registerMode = false;
  bool loading = false;
  String? error;

  @override
  void dispose() {
    emailController.dispose();
    passwordController.dispose();
    nicknameController.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (emailController.text.trim().isEmpty ||
        passwordController.text.isEmpty) {
      setState(() => error = '请输入邮箱和密码');
      return;
    }
    if (registerMode && nicknameController.text.trim().isEmpty) {
      setState(() => error = '请输入昵称');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      // [人工注释][S1-001] 登录/注册成功后才进入个人记忆空间，匿名用户不能调用个人数据 API。
      if (registerMode) {
        await widget.api.register(
          email: emailController.text,
          password: passwordController.text,
          nickname: nicknameController.text,
        );
      } else {
        await widget.api.login(
          email: emailController.text,
          password: passwordController.text,
        );
      }
      widget.onAuthenticated();
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } catch (_) {
      setState(() => error = '暂时无法连接服务器');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            JiYiSpacing.lg,
            JiYiSpacing.xxl,
            JiYiSpacing.lg,
            JiYiSpacing.xxl,
          ),
          children: [
            Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // 登录页品牌区只增强视觉识别，不增加未实现能力或营销承诺。
                    Align(
                      alignment: Alignment.centerLeft,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primaryContainer,
                          borderRadius: BorderRadius.circular(JiYiRadius.large),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(JiYiSpacing.sm),
                          child: Icon(
                            Icons.psychology_alt_outlined,
                            size: 28,
                            color: theme.colorScheme.onPrimaryContainer,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.lg),
                    Text('迹忆', style: theme.textTheme.displaySmall),
                    const SizedBox(height: JiYiSpacing.xs),
                    Text(
                      '你负责生活，我帮你记住。',
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: JiYiSpacing.xxl),
                    JiYiSectionCard(
                      title: registerMode ? '创建你的记忆空间' : '欢迎回来',
                      subtitle: registerMode
                          ? '注册后，你的记录、找回和隐私设置都归属于自己的账号。'
                          : '登录后继续查看和管理属于你的可信记忆。',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          TextField(
                            controller: emailController,
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: TextInputAction.next,
                            decoration: const InputDecoration(
                              labelText: '邮箱',
                              hintText: 'name@example.com',
                              prefixIcon: Icon(Icons.mail_outline),
                            ),
                          ),
                          const SizedBox(height: JiYiSpacing.sm),
                          TextField(
                            controller: passwordController,
                            obscureText: true,
                            textInputAction: registerMode
                                ? TextInputAction.next
                                : TextInputAction.done,
                            onSubmitted: loading || registerMode
                                ? null
                                : (_) => submit(),
                            decoration: const InputDecoration(
                              labelText: '密码',
                              prefixIcon: Icon(Icons.lock_outline),
                            ),
                          ),
                          if (registerMode) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            TextField(
                              controller: nicknameController,
                              textInputAction: TextInputAction.done,
                              onSubmitted: loading ? null : (_) => submit(),
                              decoration: const InputDecoration(
                                labelText: '昵称',
                                prefixIcon: Icon(Icons.person_outline),
                              ),
                            ),
                          ],
                          if (error != null) ...[
                            const SizedBox(height: JiYiSpacing.sm),
                            JiYiStatusBanner(
                              kind: JiYiStatusKind.error,
                              title: '未能继续',
                              message: error!,
                            ),
                          ],
                          const SizedBox(height: JiYiSpacing.md),
                          FilledButton.icon(
                            onPressed: loading ? null : submit,
                            icon: loading
                                ? const SizedBox.square(
                                    dimension: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : Icon(
                                    registerMode
                                        ? Icons.person_add_alt_1_outlined
                                        : Icons.login,
                                  ),
                            label: Text(
                              loading ? '请稍候…' : (registerMode ? '创建账号' : '登录'),
                            ),
                          ),
                          const SizedBox(height: JiYiSpacing.xs),
                          TextButton(
                            onPressed: loading
                                ? null
                                : () => setState(() {
                                    registerMode = !registerMode;
                                    error = null;
                                  }),
                            child: Text(
                              registerMode ? '已有账号？返回登录' : '第一次使用？创建账号',
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (widget.api.showDevelopmentEndpoint) ...[
                      // [人工注释][S1-FIX-007] 生产构建不渲染开发 API 信息，endpoint 只能由 build-time 配置注入。
                      const SizedBox(height: JiYiSpacing.md),
                      Text(
                        '当前开发环境 API：${widget.api.baseUrl}',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.api,
    required this.offlineQueue,
    this.sync,
    required this.onLogout,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OfflineSyncCoordinator? sync;
  final VoidCallback onLogout;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> with WidgetsBindingObserver {
  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);
  int index = 0;
  int syncGeneration = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // 登录进入生产 Shell 后立即尝试恢复当前账号的可重试 outbox。
    // coordinator 自身 single-flight，生命周期重复触发不会并发发送同一任务。
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(_autoFlush()));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_autoFlush());
    }
  }

  Future<void> _autoFlush() async {
    final owner = widget.api.authenticatedUserId;
    if (owner == null || owner.trim().isEmpty) return;
    try {
      // 空队列直接返回，既避免无意义的数据库/网络调度，也让只提供计数 seam
      // 的视觉测试不必打开真实 SQLite。数据库首次打开仍会先恢复 interrupted sending。
      final awaiting = await widget.offlineQueue.countAwaitingDelivery(owner);
      if (awaiting == 0) return;
      await _sync.flush(owner);
    } catch (_) {
      // 自动同步失败时只保留 SQLite 的真实状态，不能把本地任务伪装成 completed。
    } finally {
      if (mounted) setState(() => syncGeneration += 1);
    }
  }

  void _queueChanged() {
    if (mounted) setState(() => syncGeneration += 1);
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      const TodayPage(),
      const TimelinePage(),
      CapturePage(
        api: widget.api,
        offlineQueue: widget.offlineQueue,
        sync: _sync,
        syncGeneration: syncGeneration,
        onQueueChanged: _queueChanged,
      ),
      MemoryQueryPage(api: widget.api),
      ProfilePage(api: widget.api, onLogout: widget.onLogout),
    ];
    return Scaffold(
      body: SafeArea(child: pages[index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        // destination 数量/顺序/索引语义不变，只补充清晰的选中态图标。
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.today_outlined),
            selectedIcon: Icon(Icons.today),
            label: '今天',
          ),
          NavigationDestination(
            icon: Icon(Icons.timeline_outlined),
            selectedIcon: Icon(Icons.timeline),
            label: '时间轴',
          ),
          NavigationDestination(
            icon: Icon(Icons.add_circle_outline),
            selectedIcon: Icon(Icons.add_circle),
            label: '记一下',
          ),
          NavigationDestination(
            icon: Icon(Icons.psychology_alt_outlined),
            selectedIcon: Icon(Icons.psychology_alt),
            label: '问记忆',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: '我的',
          ),
        ],
      ),
    );
  }
}

class TodayPage extends StatelessWidget {
  const TodayPage({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return JiYiPageFrame(
      title: '今天',
      subtitle: '把重要的事记下来，需要时再找回来。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 首页只展示当前已经真实具备的记录、找回和隐私控制能力，不新增动态统计或虚构推荐。
          JiYiSectionCard(
            leading: Icon(
              Icons.shield_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '你的记忆由你控制',
            subtitle: '记录、找回、纠错、删除和暂停都由你决定。',
            child: Text(
              '先从“记一下”主动留下可信内容；需要回忆时到“问记忆”查找，并随时在“我的”里管理隐私。',
              style: theme.textTheme.bodyLarge,
            ),
          ),
          const SizedBox(height: JiYiSpacing.md),
          JiYiSectionCard(
            leading: Icon(
              Icons.fact_check_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '只展示有依据的记忆',
            child: Text(
              '没有证据时不会生成记忆；现有 Evidence 规则保持不变。',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class TimelinePage extends StatelessWidget {
  const TimelinePage({super.key});

  @override
  Widget build(BuildContext context) {
    return const JiYiPageFrame(
      title: '时间轴',
      subtitle: '按时间回看已经形成的可信记忆。',
      child: JiYiSectionCard(
        child: JiYiEmptyState(
          icon: Icons.route_outlined,
          title: '自动足迹尚未开放',
          message: '当前不会在后台自动记录位置；这里后续只会展示真实、可解释的时间记录。',
        ),
      ),
    );
  }
}

class CapturePage extends StatefulWidget {
  const CapturePage({
    super.key,
    required this.api,
    required this.offlineQueue,
    this.sync,
    this.syncGeneration = 0,
    this.onQueueChanged,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final OfflineSyncCoordinator? sync;
  final int syncGeneration;
  final VoidCallback? onQueueChanged;

  @override
  State<CapturePage> createState() => _CapturePageState();
}

class _CapturePageState extends State<CapturePage> {
  final titleController = TextEditingController();
  final contentController = TextEditingController();
  final objectController = TextEditingController();
  final locationController = TextEditingController();
  bool loading = false;
  String? result;
  int offlinePendingCount = 0;

  late final OfflineSyncCoordinator _sync =
      widget.sync ?? OfflineSyncCoordinator(api: widget.api, store: widget.offlineQueue);

  @override
  void initState() {
    super.initState();
    unawaited(_refreshOfflinePendingCount());
  }

  @override
  void didUpdateWidget(covariant CapturePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.syncGeneration != widget.syncGeneration) {
      unawaited(_refreshOfflinePendingCount());
    }
  }

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    objectController.dispose();
    locationController.dispose();
    super.dispose();
  }

  // [人工注释][S1-015] 本地队列只能使用当前认证响应里的真实 user_id；缺失身份时拒绝访问，避免无归属或跨账号记录。
  String get _ownerUserId {
    final userId = widget.api.authenticatedUserId;
    if (userId == null || userId.trim().isEmpty) {
      throw StateError('Authenticated user ID is required for offline storage');
    }
    return userId;
  }

  // [人工注释][S1-016] 待发送数量按当前 user_id 直接来自 SQLite；重启后仍能恢复，同时不暴露同机其他账号记录。
  Future<void> _refreshOfflinePendingCount() async {
    try {
      final count = await widget.offlineQueue.countAwaitingDelivery(
        _ownerUserId,
      );
      if (mounted) setState(() => offlinePendingCount = count);
    } catch (_) {
      // [人工注释][S1-016] 计数展示失败不能把真实录入流程伪装成功；保存动作仍会单独报告 SQLite 写入结果。
    }
  }

  Future<OfflineQueueItem> _flushQueued(OfflineQueueItem queued) async {
    await _sync.flush(_ownerUserId);
    final current = await widget.offlineQueue.findByClientUuid(
      _ownerUserId,
      queued.clientUuid,
    );
    if (current == null) {
      throw StateError('Offline queue item disappeared after flush');
    }
    widget.onQueueChanged?.call();
    await _refreshOfflinePendingCount();
    return current;
  }

  Future<void> saveTextMemory() async {
    final content = contentController.text.trim();
    if (content.isEmpty) return;
    final title = titleController.text.trim();
    setState(() {
      loading = true;
      result = null;
    });
    try {
      // 首次点击时先冻结发生时间并持久化 outbox；第一次在线发送和以后所有重试
      // 都复用同一 client UUID 与 occurred_at。
      final queued = await widget.offlineQueue.enqueueTextMemory(
        ownerUserId: _ownerUserId,
        title: title,
        content: content,
      );
      final current = await _flushQueued(queued);
      if (current.status == OfflineQueueStatus.completed) {
        titleController.clear();
        contentController.clear();
        setState(() => result = '✓ 已记住 · ${current.serverResourceId}');
      } else if (current.status == OfflineQueueStatus.failed && current.retryable) {
        titleController.clear();
        contentController.clear();
        setState(() => result = '✓ 已保存到本机，联网后会自动重试');
      } else {
        setState(() => result = '操作失败：${current.lastError ?? '同步失败'}');
      }
    } catch (_) {
      if (mounted) setState(() => result = '操作失败：本地保存或同步失败');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> saveObjectLocation() async {
    final objectName = objectController.text.trim();
    final locationText = locationController.text.trim();
    if (objectName.isEmpty || locationText.isEmpty) return;
    setState(() {
      loading = true;
      result = null;
    });
    try {
      // recorded_at 在 enqueue 时冻结，避免延迟同步跨过 UNKNOWN watermark 后
      // 把旧位置误当成“现在才发生”的新位置。
      final queued = await widget.offlineQueue.enqueueObjectLocation(
        ownerUserId: _ownerUserId,
        objectName: objectName,
        locationText: locationText,
      );
      final current = await _flushQueued(queued);
      if (current.status == OfflineQueueStatus.completed) {
        objectController.clear();
        locationController.clear();
        setState(() => result = '✓ 已记录当前位置 · ${current.serverResourceId}');
      } else if (current.status == OfflineQueueStatus.failed && current.retryable) {
        objectController.clear();
        locationController.clear();
        setState(() => result = '✓ 位置已保存到本机，联网后会自动重试');
      } else {
        setState(() => result = '操作失败：${current.lastError ?? '同步失败'}');
      }
    } catch (_) {
      if (mounted) setState(() => result = '操作失败：本地保存或同步失败');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> syncNow() async {
    setState(() {
      loading = true;
      result = null;
    });
    try {
      final report = await _sync.flush(_ownerUserId);
      await _refreshOfflinePendingCount();
      widget.onQueueChanged?.call();
      if (mounted) {
        setState(
          () => result =
              '同步完成：成功 ${report.completed}，待重试 ${report.retryableFailures}，需处理 ${report.blockedFailures}',
        );
      }
    } catch (_) {
      if (mounted) setState(() => result = '同步暂时无法完成');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> markObjectStale() async {
    if (objectController.text.trim().isEmpty) return;
    await _run(() async {
      // [人工注释][S1-011] “已经不在那里”必须由服务端把 CURRENT 改成 STALE，
      // 客户端不能只清空输入框或本地隐藏答案。
      await widget.api.markObjectLocationStale(objectController.text);
      locationController.clear();
      return '✓ 已标记 ${objectController.text.trim()} 已经不在原位置';
    });
  }

  Future<void> _run(Future<String> Function() action) async {
    setState(() {
      loading = true;
      result = null;
    });
    try {
      final message = await action();
      setState(() => result = message);
    } on ApiException catch (exc) {
      setState(() => result = '操作失败：${exc.message}');
    } catch (_) {
      setState(() => result = '操作失败：无法连接服务器');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final visibleResult = result == null
        ? null
        : _visibleCaptureResult(result!);
    final resultKind = result == null ? null : _captureStatusKind(result!);
    return JiYiPageFrame(
      title: '记一下',
      subtitle: '把重要的内容或物品位置清楚地记下来。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (offlinePendingCount > 0) ...[
            // 这里只展示当前账号 SQLite 已持久化的待发送事实；不新增手动同步或暗示已经上传。
            JiYiStatusBanner(
              kind: JiYiStatusKind.warning,
              title: '本机待发送',
              message: '有 $offlinePendingCount 条记录已安全保存在本机，待联网后发送。',
            ),
            const SizedBox(height: JiYiSpacing.xs),
            OutlinedButton.icon(
              onPressed: loading ? null : syncNow,
              icon: const Icon(Icons.sync),
              label: const Text('立即同步可重试记录'),
            ),
            const SizedBox(height: JiYiSpacing.md),
          ],
          JiYiSectionCard(
            leading: Icon(
              Icons.edit_note_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '写一句',
            subtitle: '适合记录临时安排、承诺、重要提醒或一段想留下的话。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: titleController,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: '标题（可选）',
                    prefixIcon: Icon(Icons.title_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  controller: contentController,
                  minLines: 3,
                  maxLines: 6,
                  decoration: const InputDecoration(
                    labelText: '内容',
                    hintText: '例如：老张周五下午来公司取合同。',
                    alignLabelWithHint: true,
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.icon(
                  onPressed: loading ? null : saveTextMemory,
                  icon: loading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.bookmark_add_outlined),
                  label: const Text('帮我记住'),
                ),
              ],
            ),
          ),
          const SizedBox(height: JiYiSpacing.md),
          JiYiSectionCard(
            leading: Icon(
              Icons.inventory_2_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '东西在哪',
            subtitle: '记录物品的当前位置；如果已经移动，可以明确标记原位置失效。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: objectController,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: '物品',
                    hintText: '例如：护照',
                    prefixIcon: Icon(Icons.inventory_2_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.sm),
                TextField(
                  controller: locationController,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration(
                    labelText: '位置',
                    hintText: '例如：书房左侧柜子第二层',
                    prefixIcon: Icon(Icons.place_outlined),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.tonalIcon(
                  onPressed: loading ? null : saveObjectLocation,
                  icon: const Icon(Icons.add_location_alt_outlined),
                  label: const Text('记录当前位置'),
                ),
                const SizedBox(height: JiYiSpacing.xs),
                OutlinedButton.icon(
                  onPressed: loading ? null : markObjectStale,
                  icon: const Icon(Icons.location_off_outlined),
                  label: const Text('已经不在那里'),
                ),
              ],
            ),
          ),
          if (visibleResult != null && resultKind != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            // 原始 result 仍保留给现有行为测试与状态机；展示层只隐藏无产品价值的内部 id/clientUuid 后缀。
            JiYiStatusBanner(kind: resultKind, message: visibleResult),
          ],
          const SizedBox(height: JiYiSpacing.md),
          // 图片与语音继续复用既有 verified media / ASR Evidence 协议；
          // 文字与物品位置仍由上方 outbox-first 路径负责，避免媒体大文件进入 SQLite。
          UnifiedMediaCaptureSection(api: widget.api),
        ],
      ),
    );
  }
}

// Capture 状态样式只根据现有结果文案分类，不改变任何成功/失败/离线判断来源。
JiYiStatusKind _captureStatusKind(String value) {
  if (value.startsWith('操作失败：')) return JiYiStatusKind.error;
  if (value.contains('已保存到本机')) return JiYiStatusKind.warning;
  return JiYiStatusKind.success;
}

// 内部 UUID/Memory id 继续存在于业务返回值中，但不直接暴露给客户；错误文案与可理解的位置结果原样保留。
String _visibleCaptureResult(String value) {
  if (!value.startsWith('✓')) return value;
  final separator = value.lastIndexOf(' · ');
  if (separator <= 0) return value;
  return value.substring(0, separator);
}

String _evidenceSourceLabel(String? sourceType) {
  const labels = <String, String>{
    'USER_TEXT': '用户文字记录',
    'USER_VOICE': '用户语音记录',
    'USER_PHOTO': '用户照片记录',
    'GPS': 'GPS 位置证据',
    'PHOTO_EXIF': '照片位置信息',
    'SYSTEM_PLACE': '系统地点识别',
    'AI_INFERENCE': 'AI 推测',
  };
  return labels[sourceType] ?? sourceType ?? '未知来源';
}

class MemoryQueryPage extends StatefulWidget {
  const MemoryQueryPage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  State<MemoryQueryPage> createState() => _MemoryQueryPageState();
}

class _MemoryQueryPageState extends State<MemoryQueryPage> {
  final controller = TextEditingController();
  Map<String, dynamic>? result;
  String? error;
  String? actionMessage;
  bool loading = false;

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> query() async {
    if (controller.text.trim().isEmpty) {
      return;
    }
    setState(() {
      loading = true;
      error = null;
      actionMessage = null;
    });
    try {
      final response = await widget.api.queryMemory(controller.text);
      setState(() => result = response);
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } catch (_) {
      setState(() => error = '暂时无法连接服务器');
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> deleteFirstMemory() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条记忆？'),
        content: const Text('删除后，这条记忆以及依赖它的当前位置答案都不能再被找回。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          // 删除语义不变，只把确认动作明确显示为危险操作，避免与普通主按钮混淆。
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }

    setState(() => loading = true);
    try {
      // [人工注释][S1-019] 只有服务端 DELETE 成功后才清空当前答案，
      // 这样“删除”才是真正影响后续检索的业务操作。
      await widget.api.deleteMemory(ids.first.toString());
      setState(() {
        result = null;
        actionMessage = '✓ 这条记忆已删除，后续查询不会再使用它';
      });
    } on ApiException catch (exc) {
      setState(() => error = exc.message);
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // G4 仅重排 Query/Evidence/删除入口的展示层；答案、Evidence、memory_ids 都继续直接使用服务端真实返回。
    final theme = Theme.of(context);
    final evidence = (result?['evidence'] as List<dynamic>? ?? const []);
    final memoryIds = (result?['memory_ids'] as List<dynamic>? ?? const []);
    final canAnswer = result?['can_answer'] == true;
    final answer = result?['answer']?.toString() ?? '';
    final certainty = result?['certainty']?.toString() ?? '未知';
    final intent = result?['intent']?.toString() ?? '未知';

    return JiYiPageFrame(
      title: '问记忆',
      subtitle: '从你自己的记录里查找；答案会把依据一起展示出来。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          JiYiSectionCard(
            leading: Icon(
              Icons.psychology_alt_outlined,
              color: theme.colorScheme.primary,
            ),
            title: '问一个问题',
            subtitle: '找不到可靠依据时，迹忆会明确告诉你，而不是猜一个答案。',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: controller,
                  textInputAction: TextInputAction.search,
                  onSubmitted: loading ? null : (_) => query(),
                  decoration: const InputDecoration(
                    labelText: '你想回忆什么？',
                    hintText: '例如：我的护照在哪里？',
                    prefixIcon: Icon(Icons.search),
                  ),
                ),
                const SizedBox(height: JiYiSpacing.md),
                FilledButton.icon(
                  onPressed: loading ? null : query,
                  icon: loading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.manage_search_outlined),
                  label: Text(loading ? '查找中…' : '从我的记忆里查找'),
                ),
              ],
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              title: '暂时无法查找',
              message: error!,
            ),
          ],
          if (actionMessage != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiStatusBanner(
              kind: JiYiStatusKind.success,
              message: actionMessage!,
            ),
          ],
          if (result != null) ...[
            const SizedBox(height: JiYiSpacing.md),
            JiYiSectionCard(
              leading: Icon(
                canAnswer ? Icons.lightbulb_outline : Icons.search_off_outlined,
                color: canAnswer
                    ? theme.colorScheme.primary
                    : theme.colorScheme.onSurfaceVariant,
              ),
              title: canAnswer ? '找到相关记忆' : '没有足够依据',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    canAnswer && answer.isNotEmpty
                        ? answer
                        : '我没有找到能够支持答案的相关记录。',
                    style: theme.textTheme.titleMedium,
                  ),
                  const SizedBox(height: JiYiSpacing.sm),
                  // certainty / intent 不被 UI 重新推断；这里只把服务端原值放入有标签的 Chip，避免弱化可信状态。
                  Wrap(
                    spacing: JiYiSpacing.xs,
                    runSpacing: JiYiSpacing.xs,
                    children: [
                      Chip(
                        avatar: const Icon(Icons.verified_outlined, size: 18),
                        label: Text('可信状态：$certainty'),
                      ),
                      Chip(
                        avatar: const Icon(Icons.category_outlined, size: 18),
                        label: Text('识别意图：$intent'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            if (evidence.isNotEmpty) ...[
              const SizedBox(height: JiYiSpacing.lg),
              Text('为什么这么回答', style: theme.textTheme.titleMedium),
              const SizedBox(height: JiYiSpacing.xs),
              Text(
                '下面是这次回答实际使用的证据。',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: JiYiSpacing.sm),
              ...evidence.map((item) {
                final e = item as Map<String, dynamic>;
                // Evidence 卡片只格式化层级；source_type/kind/occurred_at/confidence 均展示服务端真实字段。
                return Padding(
                  padding: const EdgeInsets.only(bottom: JiYiSpacing.sm),
                  child: JiYiEvidenceCard(
                    excerpt: e['excerpt']?.toString() ?? '',
                    source: _evidenceSourceLabel(e['source_type']?.toString()),
                    evidenceType: e['kind']?.toString() ?? '未知',
                    occurredAt: e['occurred_at']?.toString() ?? '未知',
                    confidence: e['confidence']?.toString() ?? '未知',
                  ),
                );
              }),
            ] else if (canAnswer) ...[
              const SizedBox(height: JiYiSpacing.md),
              // 若服务端声称可回答却没有可展示 Evidence，UI 明确暴露该异常事实，不用美化层隐藏。
              const JiYiStatusBanner(
                kind: JiYiStatusKind.warning,
                title: '没有可展示的证据',
                message: '这次响应没有返回 Evidence，请谨慎使用这个答案。',
              ),
            ],
            if (memoryIds.isNotEmpty) ...[
              const SizedBox(height: JiYiSpacing.md),
              JiYiSectionCard(
                leading: Icon(
                  Icons.delete_outline,
                  color: theme.colorScheme.error,
                ),
                title: '管理这条记忆',
                subtitle: '删除会真正影响后续检索，并同时影响依赖它的当前位置答案。',
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: theme.colorScheme.error,
                    side: BorderSide(color: theme.colorScheme.error),
                  ),
                  onPressed: loading ? null : deleteFirstMemory,
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('删除最相关记忆'),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key, required this.api, required this.onLogout});

  final JiYiApiClient api;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    // G5 只统一 Profile 的 loading/error/account 信息层级；资料仍完全来自 getProfile() 的真实响应。
    final theme = Theme.of(context);
    return JiYiPageFrame(
      title: '我的',
      subtitle: '管理账号信息、时区和隐私控制。',
      child: FutureBuilder<Map<String, dynamic>>(
        future: api.getProfile(),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const JiYiSectionCard(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: JiYiSpacing.lg),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: JiYiSpacing.sm),
                    Text('正在读取个人资料…'),
                  ],
                ),
              ),
            );
          }
          if (snapshot.hasError) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const JiYiStatusBanner(
                  kind: JiYiStatusKind.error,
                  title: '无法读取个人资料',
                  message: '请检查网络后重试；你也可以先安全退出当前账号。',
                ),
                const SizedBox(height: JiYiSpacing.md),
                OutlinedButton.icon(
                  onPressed: onLogout,
                  icon: const Icon(Icons.logout),
                  label: const Text('退出登录'),
                ),
              ],
            );
          }

          final profile = snapshot.data!;
          // 时区继续展示服务端保存的真实 IANA timezone；UI 不自行猜测或覆盖。
          final nickname = profile['nickname']?.toString() ?? '用户';
          final email = profile['email']?.toString() ?? '';
          final timezone = profile['timezone']?.toString() ?? '未知';
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              JiYiSectionCard(
                leading: CircleAvatar(
                  backgroundColor: theme.colorScheme.primaryContainer,
                  foregroundColor: theme.colorScheme.onPrimaryContainer,
                  child: const Icon(Icons.person_outline),
                ),
                title: nickname,
                subtitle: '当前登录账号',
                child: Column(
                  children: [
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.mail_outline),
                      title: const Text('邮箱'),
                      subtitle: Text(email.isEmpty ? '未提供' : email),
                    ),
                    const Divider(),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.schedule_outlined),
                      title: const Text('时区'),
                      subtitle: Text(timezone),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: JiYiSpacing.md),
              _PrivacyControls(api: api),
              const SizedBox(height: JiYiSpacing.md),
              OutlinedButton.icon(
                onPressed: onLogout,
                icon: const Icon(Icons.logout),
                label: const Text('退出登录'),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _PrivacyControls extends StatefulWidget {
  const _PrivacyControls({required this.api});

  final JiYiApiClient api;

  @override
  State<_PrivacyControls> createState() => _PrivacyControlsState();
}

class _PrivacyControlsState extends State<_PrivacyControls> {
  Map<String, dynamic>? status;
  bool loading = true;
  String? message;
  // 提示类型只控制展示样式；pause/resume 的成功失败仍以服务端结果为准。
  bool messageIsError = false;
  // statusIsStale 表示当前只能展示上一次已知状态，不能把它当成实时隐私状态。
  bool statusIsStale = false;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    if (mounted && !loading) {
      setState(() => loading = true);
    }
    try {
      final next = await widget.api.getPrivacyStatus();
      if (mounted) {
        // 刷新成功后才恢复为实时可信状态；状态值仍完全来自服务端响应。
        setState(() {
          status = next;
          statusIsStale = false;
          message = null;
          messageIsError = false;
        });
      }
    } on ApiException catch (exc) {
      if (mounted) {
        // 读取失败时绝不把未知状态推断为“未暂停”；已有状态只能作为上一次已知值展示。
        setState(() {
          statusIsStale = status != null;
          message = exc.message;
          messageIsError = true;
        });
      }
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  Future<void> apply(
    Future<Map<String, dynamic>> Function() action,
    String success,
  ) async {
    setState(() {
      // 新动作开始时只重置提示样式；暂停时长与业务状态仍由服务端决定。
      loading = true;
      message = null;
      messageIsError = false;
    });
    try {
      final next = await action();
      if (mounted) {
        setState(() {
          // success 文案仍由调用方对应真实成功动作传入；这里只设置成功视觉。
          status = next;
          statusIsStale = false;
          message = success;
          messageIsError = false;
        });
      }
    } on ApiException catch (exc) {
      if (mounted) {
        // pause/resume 的服务端错误保持 fail-visible，只加强错误状态视觉。
        setState(() {
          statusIsStale = status != null;
          message = exc.message;
          messageIsError = true;
        });
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // 隐私状态只消费服务端返回值；status 为空时必须保持 unknown，不能折算成 false。
    final theme = Theme.of(context);
    final hasKnownStatus = status != null;
    final paused = hasKnownStatus && status!['recording_paused'] == true;
    final until = hasKnownStatus ? status!['paused_until']?.toString() : null;

    if (loading && status == null) {
      return const JiYiSectionCard(
        title: '隐私与记录控制',
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: JiYiSpacing.sm),
          child: Row(
            children: [
              SizedBox.square(
                dimension: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              SizedBox(width: JiYiSpacing.sm),
              Expanded(child: Text('正在读取当前隐私状态…')),
            ],
          ),
        ),
      );
    }

    return JiYiSectionCard(
      leading: Icon(
        !hasKnownStatus
            ? Icons.error_outline
            : (paused
                  ? Icons.pause_circle_outline
                  : Icons.privacy_tip_outlined),
        color: !hasKnownStatus
            ? theme.colorScheme.error
            : (statusIsStale || paused)
            ? context.jiyiSemanticColors.warning
            : theme.colorScheme.primary,
      ),
      title: '隐私与记录控制',
      subtitle: '暂停只影响自动采集；你主动使用“记一下”仍然可以继续保存内容。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!hasKnownStatus)
            JiYiStatusBanner(
              kind: JiYiStatusKind.error,
              title: '无法确认当前隐私状态',
              message: message ?? '当前状态未知，请稍后重试。',
            )
          else
            JiYiStatusBanner(
              kind: statusIsStale
                  ? JiYiStatusKind.warning
                  : (paused ? JiYiStatusKind.warning : JiYiStatusKind.success),
              title: statusIsStale
                  ? (paused ? '上一次已知状态：自动采集已暂停' : '上一次已知状态：没有暂停自动采集')
                  : (paused ? '自动采集已暂停' : '当前没有暂停自动采集'),
              message: statusIsStale
                  ? '当前状态刷新失败，以下为上一次已知状态，可能不是最新。'
                  : paused
                  ? (until == null ? '暂停状态已生效。' : '暂停状态已生效，直到 $until。')
                  : '如果暂时不希望自动采集，可以选择一个暂停时长。',
            ),
          if (message != null && hasKnownStatus) ...[
            const SizedBox(height: JiYiSpacing.sm),
            JiYiStatusBanner(
              kind: messageIsError
                  ? JiYiStatusKind.error
                  : JiYiStatusKind.success,
              message: message!,
            ),
          ],
          const SizedBox(height: JiYiSpacing.md),
          Text('暂停时长', style: theme.textTheme.titleSmall),
          const SizedBox(height: JiYiSpacing.xs),
          // 四个时长仍调用原 pause API；这里只统一按钮层级与 loading disable 状态。
          Wrap(
            spacing: JiYiSpacing.xs,
            runSpacing: JiYiSpacing.xs,
            children: [
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () =>
                          apply(() => widget.api.pauseMemory(30), '已暂停 30 分钟'),
                child: const Text('30 分钟'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(() => widget.api.pauseMemory(60), '已暂停 1 小时'),
                child: const Text('1 小时'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () =>
                          apply(() => widget.api.pauseMemory(180), '已暂停 3 小时'),
                child: const Text('3 小时'),
              ),
              OutlinedButton(
                onPressed: loading
                    ? null
                    : () => apply(widget.api.pauseMemoryToday, '今天剩余时间已暂停'),
                child: const Text('今天'),
              ),
            ],
          ),
          const SizedBox(height: JiYiSpacing.md),
          // 恢复按钮仍只在服务端状态 paused=true 时可用；历史 pause interval 与禁止补传语义不变。
          FilledButton.icon(
            onPressed: loading || !paused
                ? null
                : () => apply(widget.api.resumeMemory, '已恢复自动记录'),
            icon: loading
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow_rounded),
            label: const Text('恢复记录'),
          ),
        ],
      ),
    );
  }
}
