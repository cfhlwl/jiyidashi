import 'package:flutter/material.dart';

import 'api_client.dart';

class JiYiApp extends StatefulWidget {
  const JiYiApp({super.key, this.api});

  final JiYiApiClient? api;

  @override
  State<JiYiApp> createState() => _JiYiAppState();
}

class _JiYiAppState extends State<JiYiApp> {
  late final JiYiApiClient api = widget.api ?? JiYiApiClient();
  bool authenticated = false;

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
  const AppShell({super.key, required this.api, required this.onLogout});

  final JiYiApiClient api;
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
      CapturePage(api: widget.api),
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
      subtitle: 'Stage 1 先把“记住 → 找回 → 相信”做扎实。',
      child: _InfoCard(title: '第一批真实闭环', detail: '现在可以登录、写下一条记忆、记录物品位置，并从服务端 Evidence 中找回答案。'),
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
  const CapturePage({super.key, required this.api});

  final JiYiApiClient api;

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

  @override
  void dispose() {
    titleController.dispose();
    contentController.dispose();
    objectController.dispose();
    locationController.dispose();
    super.dispose();
  }

  Future<void> saveTextMemory() async {
    if (contentController.text.trim().isEmpty) return;
    await _run(() async {
      final memory = await widget.api.createTextMemory(
        title: titleController.text,
        content: contentController.text,
      );
      contentController.clear();
      return '✓ 已记住 · ${memory['id']}';
    });
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

  Future<void> _run(Future<String> Function() action) async {
    setState(() {
      loading = true;
      result = null;
    });
    try {
      final message = await action();
      setState(() => result = message);
    } on ApiException catch (exc) {
      setState(() => result = '保存失败：${exc.message}');
    } catch (_) {
      setState(() => result = '保存失败：无法连接服务器');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      title: '记一下',
      subtitle: '第一批先支持文字记忆和“东西在哪”。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
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

  @override
  Widget build(BuildContext context) {
    final evidence = (result?['evidence'] as List<dynamic>? ?? const []);
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
              _InfoCard(title: profile['nickname']?.toString() ?? '用户', detail: '${profile['email'] ?? ''}\n时区：${profile['timezone']}'),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onLogout, child: const Text('退出登录')),
            ],
          );
        },
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
