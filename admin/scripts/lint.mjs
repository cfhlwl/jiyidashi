import { readdir, readFile } from 'node:fs/promises'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../src', import.meta.url))

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) files.push(...await walk(path))
    else if (['.ts', '.tsx'].includes(extname(entry.name))) files.push(path)
  }
  return files
}

const violations = []
for (const file of await walk(root)) {
  const source = await readFile(file, 'utf8')
  const name = relative(root, file).replaceAll('\\', '/')
  const rules = [
    ['浏览器持久化不能保存管理凭证', /\b(?:localStorage|sessionStorage)\b/g],
    ['禁止直接插入不可信 HTML', /\bdangerouslySetInnerHTML\b/g],
    ['生产前端禁止调试控制台输出', /\bconsole\.(?:log|debug|info|warn|error)\b/g],
  ]
  if (name !== 'api.ts') {
    rules.push(['网络请求必须经过统一 Admin API boundary', /\bfetch\s*\(/g])
    rules.push(['视觉 fixture 只能由统一 API boundary 引入', /from ['"].*fixtures['"]/g])
  }
  for (const [message, pattern] of rules) {
    if (pattern.test(source)) violations.push(`${name}: ${message}`)
  }
}

if (violations.length) {
  console.error(violations.join('\n'))
  process.exit(1)
}

console.log('Admin lint PASS')
