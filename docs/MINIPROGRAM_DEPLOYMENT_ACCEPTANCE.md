<!-- [人工注释][S1-005] 本文记录微信小程序真实图片媒体链在真机/外测前必须完成的部署验收；CI 构建成功不能替代微信合法域名与真实 COS/OSS 网络策略验证。 -->
# 微信小程序图片媒体链部署验收

## 适用范围

本验收只覆盖 Stage 1C 主动拍照 / 主动选图的真实媒体链：

`chooseMedia → POST /media/uploads → signed raw PUT → POST /complete → READY → POST /media/{id}/memory → USER_PHOTO Evidence`

不包含 OCR、Vision、ASR、后台相册扫描或 Stage 2 能力。

## 真机 / 外测前硬门禁

<!-- [人工注释][S1-005] signed PUT URL 由服务端临时签发，客户端不能硬编码 provider/bucket；但微信运行时仍要求实际访问域名已经配置为 request 合法域名。 -->
1. **正式 API 域名**必须是 HTTPS，并加入微信小程序后台的 `request` 合法域名。
2. **signed PUT 实际对象存储域名**也必须加入 `request` 合法域名。该域名应以生产环境服务端实际签发的 COS / OSS URL 为准，不能只验证 CI 中的占位域名。
3. 如果对象存储切换为自定义域名、CDN 域名或其他 provider endpoint，必须重新核对微信合法域名配置；客户端不得为了绕过平台策略降级到 HTTP、代理假上传或写死 bucket / object key。
4. 域名未配置、证书异常、微信平台拒绝请求时，验收结论必须为 **HOLD**；不得把失败路径伪装为“已记录”。

## 真实链路验收步骤

<!-- [人工注释][S1-005] 真机验收必须证明微信网络平台策略、真实对象存储和服务端 READY/Evidence 门禁一起工作，而不是只证明 Taro 能编译。 -->
在真实微信小程序运行环境、真实生产/预生产 API 与真实 COS/OSS 上至少完成一次：

1. 用户主动拍照或选择一张支持格式图片。
2. `POST /media/uploads` 成功，服务端返回短时 signed PUT。
3. 小程序对该真实对象存储 URL 执行 raw `PUT` 成功。
4. `POST /media/{id}/complete` 成功，媒体状态由服务端确认进入 `READY`。
5. `POST /media/{id}/memory` 成功，生成对应 `USER_PHOTO` Memory / Evidence。
6. 通过现有查询接口读取该 Memory，确认 Evidence 可回查且 `media_id` 与服务端关联一致。
7. 再验证至少一个失败路径（例如在专用测试环境暂时不满足对象存储合法域名或签名条件）：小程序必须显示失败，不能进入 recorded，也不能创建假 Memory。不得为了测试而破坏生产环境合法域名配置。

## 验收记录

- 当前 PR #9 的自动 CI 只验证 TypeScript、capture workflow tests 与 production WeChat build。
- 真实 COS/OSS + 微信 `request` 合法域名属于**部署/真机验收项**，在具备真实小程序后台和对象存储环境后执行。
- 未完成上述真机验收前，不应把该项描述为“真实 provider 已验证”。
