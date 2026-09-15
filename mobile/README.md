# Flutter 主客户端

该目录是 Android / iOS 共用 Flutter 主工程的业务骨架。

当前已锁定的一级导航：

1. 今天
2. 时间轴
3. 记一下
4. 问记忆
5. 我的

## 原生模块边界

后台定位不会长期依赖普通 Flutter 插件。第二阶段分别实现：

- Android Native Location Module
- iOS CoreLocation Module

统一暴露：

```text
startTracking()
pauseTracking()
resumeTracking()
stopTracking()
getTrackingStatus()
```

Flutter 层负责业务 UI 与同步状态，不直接实现操作系统后台保活策略。
