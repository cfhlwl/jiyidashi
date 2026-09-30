# Admin Product Language

生产 Admin Console 使用面向运营人员的产品语言。内部实现词汇不能作为普通 UI 主文案。

## 普通 UI 规则

页面应回答：发生了什么、是否需要处理、接下来可以做什么。

正常 UI 使用“账号注销处理中”“数据删除失败”“AI 服务”“语音识别服务”“记忆检索服务”“文件存储”“服务状态”“操作记录”“任务编号”等产品词。

UUID、enum、payload、cursor、revision、traceback、stack trace、provider、backend、raw JSON、migration head、框架验证错误、数据库异常、raw status/role 等词不能作为主文案。

精确内部标识只允许在用户主动展开的 TechnicalDetails 中出现。

## 稳定映射

admin/src/productLanguage.ts 统一维护管理员职责、会员方案、Family 身份与授权类别、删除状态、安全级别和类别、通知状态、Admin audit action/target 的人类可读映射。未知内部值只能映射到安全 fallback，不直接回显。

## 错误边界

admin/src/api.ts 是浏览器唯一网络边界。后端 detail 只能作为受审核 safe-error dictionary 的 key 使用，任意后端响应文本不得直接显示。

## Regression Gate

npm run language 递归扫描真实 production Admin UI 的可见 sink，包括 JSX 文本和 title/label/description/message/placeholder/confirmation 等字段。TechnicalDetails 被显式排除。Gate 同时设置最小 sink 数量，防止扫描范围意外缩小后假通过。