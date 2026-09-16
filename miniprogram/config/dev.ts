import type { UserConfigExport } from '@tarojs/cli'

const apiBase = process.env.JIYI_API_BASE_URL?.trim() || 'http://127.0.0.1:8000/v1'

export default {
  env: {
    NODE_ENV: '"development"',
  },
  // [人工注释][S1-FIX-007] 开发构建允许显式覆盖 API；生产配置会强制真实 HTTPS endpoint 并关闭编辑入口。
  defineConstants: {
    JIYI_API_BASE_URL: JSON.stringify(apiBase),
    JIYI_ALLOW_API_BASE_EDIT: JSON.stringify(true),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
