import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'offline_queue.dart';

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
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF446A57),
        scaffoldBackgroundColor: const Color(0xFFF7F8F6),
      ),
      home: authenticated
          ? AppShell(
              api: api,
              offlineQueue: offlineQueue,
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
    if (emailController.text.trim().isEmpty || passwordController.text.isEmpty) {
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
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 48, 24, 28),
          children: [
            Text(
              '迹忆',
              style: Theme.of(context).textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              '你负责生活，我帮你记住。',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 36),
            TextField(
              controller: emailController,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                labelText: '邮箱',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: passwordController,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: '密码',
                border: OutlineInputBorder(),
              ),
            ),
            if (registerMode) ...[
              const SizedBox(height: 14),
              TextField(
                controller: nicknameController,
                decoration: const InputDecoration(
                  labelText: '昵称',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
            if (error != null) ...[
              const SizedBox(height: 12),
              Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            const SizedBox(height: 18),
            FilledButton(
              onPressed: loading ? null : submit,
              child: Text(loading ? '请稍候…' : (registerMode ? '创建账号' : '登录')),
            ),
            TextButton(
              onPressed: loading
                  ? null
                  : () => setState(() {
                        registerMode = !registerMode;
                        error = null;
                      }),
              child: Text(registerMode ? '已有账号？登录' : '第一次使用？创建账号'),
            ),
            if (widget.api.showDevelopmentEndpoint) ...[
              // [人工注释][S1-FIX-007] 生产构建不渲染开发 API 信息，endpoint 只能由 build-time 配置注入。
              const SizedBox(height: 20),
              Text(
                '当前开发环境 API：${widget.api.baseUrl}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
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
    required this.onLogout,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;
  final VoidCallback onLogout;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      const TodayPage(),
      const TimelinePage(),
      CapturePage(api: widget.api, offlineQueue: widget.offlineQueue),
      MemoryQueryPage(api: widget.api),
      ProfilePage(api: widget.api, onLogout: widget.onLogout),
    ];
    return Scaffold(
      body: SafeArea(child: pages[index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.today_outlined), label: '今天'),
          NavigationDestination(icon: Icon(Icons.timeline_outlined), label: '时间轴'),
          NavigationDestination(icon: Icon(Icons.add_circle_outline), label: '记一下'),
          NavigationDestination(icon: Icon(Icons.psychology_alt_outlined), label: '问记忆'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: '我的'),
        ],
      ),
    );
  }
}

class PageFrame extends StatelessWidget {
  const PageFrame({super.key, required this.title, required this.child, this.subtitle});

  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 22, 20, 28),
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w700)),
        if (subtitle != null) ...[
          const SizedBox(height: 6),
          Text(subtitle!, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ],
        const SizedBox(height: 22),
        child,
      ],
    );
  }
}

class TodayPage extends StatelessWidget {
  const TodayPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const PageFrame(
      title: '今天',
      subtitle: 'Stage 1 继续完善“记住 → 找回 → 纠错 → 删除 → 暂停”。',
      child: _InfoCard(
        title: '你的记忆由你控制',
        detail: '现在除了记录与找回，还可以标记物品已经不在原位置、删除记忆，并随时暂停或恢复自动记录。',
      ),
    );
  }
}

class TimelinePage extends StatelessWidget {
  const TimelinePage({super.key});

  @override
  Widget build(BuildContext context) {
    return const PageFrame(
      title: '时间轴',
      subtitle: '自动足迹仍属于 Stage 2，本阶段不提前接入。',
      child: _InfoCard(title: '暂未开放自动足迹', detail: '当前只展示用户主动记录的可信记忆；后台定位会在独立阶段开发。'),
    );
  }
}

class CapturePage extends StatefulWidget {
  const CapturePage({
    super.key,
    required this.api,
    required this.offlineQueue,
  });

  final JiYiApiClient api;
  final OfflineQueueStore offlineQueue;

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

  @override
  void initState() {
    super.initState();
    unawaited(_refreshOfflinePendingCount());
  }

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    objectController.dispose();
    locationController.dispose();
    super.dispose();
  }

  // [人工注释][S1-016] 待发送数量直接来自 SQLite；App 重启后仍能看到未完成本地记录，而不是依赖内存计数。
  Future<void> _refreshOfflinePendingCount() async {
    try {
      final count = await widget.offlineQueue.countAwaitingDelivery();
      if (mounted) setState(() => offlinePendingCount = count);
    } catch (_) {
      // 计数展示失败不能把真实录入流程伪装成功；保存动作仍会单独报告 SQLite 写入结果。
    }
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
      final memory = await widget.api.createTextMemory(
        title: title,
        content: content,
      );
      titleController.clear();
      contentController.clear();
      setState(() => result = '✓ 已记住 · ${memory['id']}');
    } on ApiException catch (exc) {
      // [人工注释][S1-016] 服务端已明确返回的认证/校验/业务错误不是“离线”；禁止把真实失败转成本地假成功。
      setState(() => result = '操作失败：${exc.message}');
    } catch (_) {
      try {
        // [人工注释][S1-015] 连接层失败时先 await SQLite 持久化成功，再清输入框并展示“已保存到本机”。
        final queued = await widget.offlineQueue.enqueueTextMemory(
          title: title,
          content: content,
        );
        titleController.clear();
        contentController.clear();
        await _refreshOfflinePendingCount();
        if (mounted) {
          setState(
            () => result =
                '✓ 已保存到本机，待联网后发送 · ${queued.clientUuid}',
          );
        }
      } catch (_) {
        if (mounted) {
          setState(() => result = '操作失败：无法连接服务器，且本地保存失败');
        }
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> saveObjectLocation() async {
    if (objectController.text.trim().isEmpty || locationController.text.trim().isEmpty) return;
    await _run(() async {
      final location = await widget.api.rememberObjectLocation(
        objectName: objectController.text,
        locationText: locationController.text,
      );
      return '✓ 已记录 ${objectController.text.trim()} 的当前位置 · ${location['location_text']}';
    });
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
    return PageFrame(
      title: '记一下',
      subtitle: '记录新的可信记忆，也可以明确纠正已经失效的位置。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (offlinePendingCount > 0) ...[
            // [人工注释][S1-016] 本批只展示本机待发送事实，不提供“立即同步”按钮，避免越界实现 S1-017。
            _InfoCard(
              title: '本机待发送',
              detail: '有 $offlinePendingCount 条记录已安全保存在本机，等待后续联网同步。',
            ),
            const SizedBox(height: 12),
          ],
          Card(
            elevation: 0,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('写一句', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 12),
                  TextField(controller: titleController, decoration: const InputDecoration(labelText: '标题（可选）')),
                  const SizedBox(height: 8),
                  TextField(
                    controller: contentController,
                    minLines: 3,
                    maxLines: 6,
                    decoration: const InputDecoration(border: OutlineInputBorder(), hintText: '例如：老张周五下午来公司取合同。'),
                  ),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: loading ? null : saveTextMemory, child: const Text('帮我记住')),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            elevation: 0,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('东西在哪', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 12),
                  TextField(controller: objectController, decoration: const InputDecoration(labelText: '物品', hintText: '护照')),
                  const SizedBox(height: 8),
                  TextField(controller: locationController, decoration: const InputDecoration(labelText: '位置', hintText: '书房左侧柜子第二层')),
                  const SizedBox(height: 12),
                  FilledButton.tonal(onPressed: loading ? null : saveObjectLocation, child: const Text('记录当前位置')),
                  const SizedBox(height: 8),
                  OutlinedButton(onPressed: loading ? null : markObjectStale, child: const Text('已经不在那里')),
                ],
              ),
            ),
          ),
          if (result != null) ...[
            const SizedBox(height: 12),
            Text(result!),
          ],
        ],
      ),
    );
  }
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
    if (controller.text.trim().isEmpty) return;
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
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> deleteFirstMemory() async {
    final ids = result?['memory_ids'] as List<dynamic>? ?? const [];
    if (ids.isEmpty) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条记忆？'),
        content: const Text('删除后，这条记忆以及依赖它的当前位置答案都不能再被找回。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true) return;

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
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final evidence = (result?['evidence'] as List<dynamic>? ?? const []);
    final memoryIds = (result?['memory_ids'] as List<dynamic>? ?? const []);
    return PageFrame(
      title: '问记忆',
      subtitle: '答案必须来自你的真实 Evidence。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: controller,
            decoration: const InputDecoration(
              labelText: '你想回忆什么？',
              hintText: '例如：我的护照在哪里？',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(onPressed: loading ? null : query, child: Text(loading ? '查找中…' : '从我的记忆里查找')),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          if (actionMessage != null) ...[
            const SizedBox(height: 12),
            Text(actionMessage!),
          ],
          if (result != null) ...[
            const SizedBox(height: 18),
            Card(
              elevation: 0,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      result!['can_answer'] == true ? (result!['answer']?.toString() ?? '') : '我没有找到相关记录。',
                      style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 8),
                    Text('可信状态：${result!['certainty']} · 意图：${result!['intent']}'),
                  ],
                ),
              ),
            ),
            ...evidence.map((item) {
              final e = item as Map<String, dynamic>;
              // [人工注释][S1-FIX-002] kind 是证据实体类型；“来源”必须展示服务端返回的真实 source_type。
              return Card(
                elevation: 0,
                child: ListTile(
                  leading: const Icon(Icons.fact_check_outlined),
                  title: Text(e['excerpt']?.toString() ?? ''),
                  subtitle: Text(
                    '来源：${_evidenceSourceLabel(e['source_type']?.toString())}\n'
                    '证据类型：${e['kind']} · 时间：${e['occurred_at']}\n'
                    '可信度：${e['confidence']}',
                  ),
                ),
              );
            }),
            if (memoryIds.isNotEmpty) ...[
              const SizedBox(height: 8),
              OutlinedButton(
                onPressed: loading ? null : deleteFirstMemory,
                child: const Text('删除最相关记忆'),
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
    return PageFrame(
      title: '我的',
      subtitle: '正式账号与个人记忆空间。',
      child: FutureBuilder<Map<String, dynamic>>(
        future: api.getProfile(),
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('无法读取个人资料'),
                const SizedBox(height: 12),
                OutlinedButton(onPressed: onLogout, child: const Text('退出登录')),
              ],
            );
          }
          final profile = snapshot.data!;
          // [人工注释][S1-002] 展示服务端保存的时区，后续时间轴自然日都以该 IANA timezone 为准。
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _InfoCard(
                title: profile['nickname']?.toString() ?? '用户',
                detail: '${profile['email'] ?? ''}\n时区：${profile['timezone']}',
              ),
              const SizedBox(height: 12),
              _PrivacyControls(api: api),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onLogout, child: const Text('退出登录')),
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

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    try {
      final next = await widget.api.getPrivacyStatus();
      if (mounted) setState(() => status = next);
    } on ApiException catch (exc) {
      if (mounted) setState(() => message = exc.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> apply(
    Future<Map<String, dynamic>> Function() action,
    String success,
  ) async {
    setState(() {
      loading = true;
      message = null;
    });
    try {
      final next = await action();
      if (mounted) {
        setState(() {
          status = next;
          message = success;
        });
      }
    } on ApiException catch (exc) {
      if (mounted) setState(() => message = exc.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final paused = status?['recording_paused'] == true;
    final until = status?['paused_until']?.toString();
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('记忆暂停', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(paused ? '自动记录已暂停${until == null ? '' : '，直到 $until'}' : '自动记录当前开启'),
            const SizedBox(height: 12),
            // [人工注释][S1-023] 暂停只影响自动采集；用户主动“记一下”仍可继续使用。
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton(onPressed: loading ? null : () => apply(() => widget.api.pauseMemory(30), '已暂停 30 分钟'), child: const Text('30 分钟')),
                OutlinedButton(onPressed: loading ? null : () => apply(() => widget.api.pauseMemory(60), '已暂停 1 小时'), child: const Text('1 小时')),
                OutlinedButton(onPressed: loading ? null : () => apply(() => widget.api.pauseMemory(180), '已暂停 3 小时'), child: const Text('3 小时')),
                OutlinedButton(onPressed: loading ? null : () => apply(widget.api.pauseMemoryToday, '今天剩余时间已暂停'), child: const Text('今天')),
              ],
            ),
            const SizedBox(height: 8),
            // [人工注释][S1-024] 恢复后历史 pause interval 仍保留，暂停期间自动数据不能延迟补传。
            FilledButton(
              onPressed: loading || !paused ? null : () => apply(widget.api.resumeMemory, '已恢复自动记录'),
              child: const Text('恢复记录'),
            ),
            if (message != null) ...[
              const SizedBox(height: 8),
              Text(message!),
            ],
          ],
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.title, required this.detail});

  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(detail),
          ],
        ),
      ),
    );
  }
}
