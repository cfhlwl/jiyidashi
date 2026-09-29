import 'package:flutter/material.dart';

import '../api_client.dart';
import 'life_page.dart';
import 'people_page.dart';

class V2HomePage extends StatelessWidget {
  const V2HomePage({super.key, required this.api});

  final JiYiApiClient api;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('个人记忆图谱'),
          bottom: const TabBar(
            tabs: [
              Tab(text: '人物', icon: Icon(Icons.people_outline)),
              Tab(text: '人生', icon: Icon(Icons.auto_stories_outlined)),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            PeoplePage(api: api),
            LifePage(api: api),
          ],
        ),
      ),
    );
  }
}
