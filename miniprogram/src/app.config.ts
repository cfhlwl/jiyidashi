export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/summaries/index',
    'pages/life/index',
    'pages/place-detail/index',
    'pages/capture/index',
    'pages/query/index',
    'pages/family/index',
    'pages/profile/index',
    'pages/people/index',
    'pages/person-detail/index',
    'pages/graph-neighborhood/index',
  ],
  window: {
    navigationBarTitleText: '迹忆',
    navigationBarBackgroundColor: '#f7f4ee',
    backgroundColor: '#f7f4ee',
  },
  tabBar: {
    color: '#687480',
    selectedColor: '#356A9A',
    backgroundColor: '#fffdf9',
    borderStyle: 'white',
    list: [
      { pagePath: 'pages/index/index', text: '今天' },
      { pagePath: 'pages/query/index', text: '记忆' },
      { pagePath: 'pages/life/index', text: '人生' },
      { pagePath: 'pages/family/index', text: '家庭' },
      { pagePath: 'pages/profile/index', text: '我的' },
    ],
  },
  // [人工注释][S1-005] 图片选择使用用户主动触发的 chooseMedia；当前微信/Taro 协议不要求、也不允许
  // 将 chooseMedia 写入 requiredPrivateInfos。不会后台扫描或主动读取相册。
  // [人工注释][S1-004] 语音本轮只申请本地录音权限并生成临时文件，不上传、不 ASR、不创建语音 Memory。
  permission: {
    'scope.record': {
      desc: '用于用户主动录制一段仅保存在本地临时目录的语音',
    },
  },
})
