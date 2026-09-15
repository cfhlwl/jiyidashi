export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/capture/index',
    'pages/query/index',
    'pages/family/index',
    'pages/profile/index',
  ],
  window: {
    navigationBarTitleText: '迹忆',
    navigationBarBackgroundColor: '#f7f8f6',
    backgroundColor: '#f7f8f6',
  },
  tabBar: {
    color: '#66706a',
    selectedColor: '#446A57',
    list: [
      { pagePath: 'pages/index/index', text: '今天' },
      { pagePath: 'pages/capture/index', text: '记一下' },
      { pagePath: 'pages/query/index', text: '问记忆' },
      { pagePath: 'pages/family/index', text: '家庭' },
      { pagePath: 'pages/profile/index', text: '我的' },
    ],
  },
})
