<!-- [人工注释][DOC-PROGRESS-001] ROADMAP 只保留高层路线，实时状态以 DEVELOPMENT_PROGRESS.md 为唯一准确信息源。 -->
# 开发路线

> 实时开发状态、任务 ID、PR/审查进度统一维护在 `docs/DEVELOPMENT_PROGRESS.md`。  
> 人工新增或修改代码的注释要求见 `docs/CODE_ANNOTATION_RULES.md`。

## Stage 1 — 记得住

当前基础工程属于这个阶段。

Foundation 当前状态：**🔵 进行中（PR #1 第二轮正式审查）**。

已实现但尚未合并 main 的 foundation 能力包括：

- Memory 数据模型
- Evidence 数据模型
- 对象/物品位置历史
- 无证据不回答
- AI inference 与 confirmed fact 隔离
- 隐私暂停服务端门禁与历史区间
- ObjectLocation CURRENT 唯一性与离线旧记录防回滚
- 用户时区自然日
- 中文基础记忆查询
- Alembic migration baseline
- Flutter Android/iOS 标准工程与 CI
- 微信小程序标准工程与 CI

Stage 1 后续核心任务：

- 正式用户登录
- 文字/语音/照片真实录入链路
- 语音上传 + ASR
- 图片上传 + 对象存储直传
- 客户端本地 SQLite/离线队列
- API 客户端接线
- “东西在哪”完整前后端闭环
- Evidence 答案展示
- 数据导出/彻底删除/账号注销

## Stage 2 — 自动记

Foundation 未通过正式审查前不进入本阶段。

- Android 原生后台定位
- iOS CoreLocation 后台定位
- Flutter Location Bridge
- 智能采样与运动状态
- Location Point 去重与批量同步
- Visit 聚类
- Place 自动命名与用户纠正
- 自动时间轴
- 今日足迹
- 原始位置生命周期

## Stage 3 — 懂生活

- AI Gateway
- Memory Pipeline
- Intent Router
- OCR
- Vision
- Reminder 提取
- Daily / Monthly / Annual Summary
- pgvector
- Embedding
- Memory RAG
- Evidence Ranking
- 事实 / 证据 / AI 推断严格区分
- False Memory Rate 质量指标

## Stage 4 — 连接家庭

- 家庭邀请
- 权限矩阵
- 小程序家庭端
- 长辈模式
- 到家提醒
- 紧急共享
- 家庭隐私审计

## V2 — Personal Memory Graph

- Person 人物模型
- 人物关系与相关记忆
- Place / Person / Object / Event 统一图谱
- 人生事件与人生阶段
- 长期记忆推理
- 年度电子回忆录
- 人生回忆录

## V3 — AI 人生助手与硬件扩展

- 跨多年人生问答与总结
- 家庭数字档案
- 记忆按钮 / AI 挂件（需求验证后）
- 可穿戴快捷语音记录
- 实体回忆录打印

## 明确后置 / V1 不做

- 24 小时录音
- 人脸识别
- 疾病诊断
- 老年痴呆诊断或治疗建议
- 自动全量扫描相册
- 社交社区
- 商城 / 广告 / 新闻资讯
- AI 数字人
