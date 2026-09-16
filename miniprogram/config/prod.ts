import type { UserConfigExport } from '@tarojs/cli'

const apiBase = process.env.JIYI_API_BASE_URL?.trim()
if (!apiBase || !apiBase.startsWith('https://') || /localhost|127\.0\.0\.1/.test(apiBase)) {
  throw new Error('Production JIYI_API_BASE_URL must be a non-local HTTPS URL')
}

export default {
  env: {
    NODE_ENV: '"production"',
  },
  // [人工注释][S1-FIX-007] 生产构建只接受 build-time HTTPS API，并从产物中关闭普通用户 API 编辑入口。
  defineConstants: {
    JIYI_API_BASE_URL: JSON.stringify(apiBase),
    JIYI_ALLOW_API_BASE_EDIT: JSON.stringify(false),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
