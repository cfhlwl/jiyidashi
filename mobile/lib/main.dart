import 'package:flutter/material.dart';

void main() {
  runApp(const JiYiApp());
}

class JiYiApp extends StatelessWidget {
  const JiYiApp({super.key});

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
      home: const AppShell(),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int index = 0;

  static const pages = <Widget>[
    TodayPage(),
    TimelinePage(),
    CapturePage(),
    MemoryQueryPage(),
    ProfilePage(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(child: pages[index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
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

class PageFrame extends StatelessWidget {
  const PageFrame({
    super.key,
    required this.title,
    required this.child,
    this.subtitle,
  });

  final String title;
  final String? subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 22, 20, 28),
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 6),
          Text(
            subtitle!,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
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
    return PageFrame(
      title: '今天',
      subtitle: '你负责生活，我帮你记住。',
      child: Column(
        children: [
          const _SummaryCard(),
          const SizedBox(height: 16),
          ...const [
            _TimelineCard(
              time: '08:52',
              title: '等待自动足迹',
              detail: 'V1 第二阶段接入 Android / iOS 原生后台定位。',
              icon: Icons.location_on_outlined,
            ),
            SizedBox(height: 12),
            _TimelineCard(
              time: '现在',
              title: '先记住一件重要的事',
              detail: '例如：“护照放在书房左侧柜子第二层”。',
              icon: Icons.bookmark_add_outlined,
            ),
          ],
        ],
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: const [
            _Metric(value: '0', label: '地点'),
            _Metric(value: '0', label: '记忆'),
            _Metric(value: '0', label: '照片'),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          value,
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.w700,
              ),
        ),
        Text(label),
      ],
    );
  }
}

class _TimelineCard extends StatelessWidget {
  const _TimelineCard({
    required this.time,
    required this.title,
    required this.detail,
    required this.icon,
  });

  final String time;
  final String title;
  final String detail;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$time · $title',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 6),
                  Text(detail),
                ],
              ),
            ),
          ],
        ),
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
      subtitle: '过去发生过什么，都从这里找回来。',
      child: _EmptyState(
        icon: Icons.timeline,
        title: '还没有时间轴',
        detail: '开始记录后，你的地点、主动记忆和重要事件会按时间排列。',
      ),
    );
  }
}

class CapturePage extends StatelessWidget {
  const CapturePage({super.key});

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      title: '记一下',
      subtitle: '不用分类，先把事情说出来。',
      child: Column(
        children: const [
          _ActionTile(
            icon: Icons.mic_none,
            title: '说一句',
            detail: '“帮我记住，合同放书房第三层。”',
          ),
          SizedBox(height: 12),
          _ActionTile(
            icon: Icons.edit_note,
            title: '写一句',
            detail: '适合安静环境或需要精确输入。',
          ),
          SizedBox(height: 12),
          _ActionTile(
            icon: Icons.photo_camera_outlined,
            title: '拍一下',
            detail: '照片会作为记忆证据，而不是让 AI 凭空猜测。',
          ),
          SizedBox(height: 12),
          _ActionTile(
            icon: Icons.inventory_2_outlined,
            title: '东西在哪',
            detail: '记录护照、钥匙、证件、合同等物品最后位置。',
          ),
        ],
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: ListTile(
        leading: CircleAvatar(child: Icon(icon)),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(detail),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }
}

class MemoryQueryPage extends StatefulWidget {
  const MemoryQueryPage({super.key});

  @override
  State<MemoryQueryPage> createState() => _MemoryQueryPageState();
}

class _MemoryQueryPageState extends State<MemoryQueryPage> {
  final controller = TextEditingController();

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      title: '问记忆',
      subtitle: '没有证据时，迹忆会明确告诉你“没有找到”。',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: controller,
            decoration: const InputDecoration(
              labelText: '你想回忆什么？',
              hintText: '例如：我的护照在哪里？',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.search),
            ),
            minLines: 1,
            maxLines: 3,
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () {},
            icon: const Icon(Icons.psychology_alt),
            label: const Text('从我的记忆里查找'),
          ),
          const SizedBox(height: 22),
          const _EmptyState(
            icon: Icons.fact_check_outlined,
            title: '答案会带证据',
            detail: '时间、来源和可信度会和答案一起展示，避免 AI 编造人生经历。',
          ),
        ],
      ),
    );
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      title: '我的',
      subtitle: '记忆属于你，控制权也必须属于你。',
      child: Column(
        children: const [
          _SettingsTile(icon: Icons.family_restroom, title: '家庭成员'),
          _SettingsTile(icon: Icons.pause_circle_outline, title: '暂停记录'),
          _SettingsTile(icon: Icons.location_on_outlined, title: '位置权限'),
          _SettingsTile(icon: Icons.lock_outline, title: '隐私与记忆'),
          _SettingsTile(icon: Icons.download_outlined, title: '导出我的数据'),
          _SettingsTile(icon: Icons.accessibility_new, title: '长辈模式'),
        ],
      ),
    );
  }
}

class _SettingsTile extends StatelessWidget {
  const _SettingsTile({required this.icon, required this.title});

  final IconData icon;
  final String title;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: ListTile(
        leading: Icon(icon),
        title: Text(title),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 36),
        child: Column(
          children: [
            Icon(icon, size: 42),
            const SizedBox(height: 12),
            Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(detail, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}
