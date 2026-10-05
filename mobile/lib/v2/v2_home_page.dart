import 'package:flutter/material.dart';

import '../api_client.dart';
import '../media_presentation_cache.dart';
import 'life_page.dart';
import 'people_page.dart';

class V2HomePage extends StatelessWidget {
  const V2HomePage({
    super.key,
    required this.api,
    this.mediaCache,
  });

  final JiYiApiClient api;
  final LocalMediaCache? mediaCache;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('记忆与人生'),
          bottom: const TabBar(
            tabs: [
              Tab(text: '重要的人', icon: Icon(Icons.people_outline)),
              Tab(text: '我的人生', icon: Icon(Icons.auto_stories_outlined)),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            PeoplePage(api: api),
            LifePage(
              api: api,
              mediaCache: mediaCache,
            ),
          ],
        ),
      ),
    );
  }
}
