import { createHash } from 'node:crypto'
import {
  createReadStream,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'
import { chromium } from 'playwright'

const root = new URL('../dist/', import.meta.url).pathname
const out = new URL('../visual-artifacts/', import.meta.url).pathname

const scenes = [
  'today', 'timeline', 'capture', 'memory', 'people', 'life',
  'family', 'profile', 'summary', 'states', 'elder',
  'account-security', 'account-security-empty',
]
const widths = [320, 390, 430]
const height = 844

mkdirSync(out, { recursive: true })

function listFiles(base, relative = '') {
  const absolute = join(base, relative)
  const entries = readdirSync(absolute, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const next = relative ? join(relative, entry.name) : entry.name
    if (entry.isDirectory()) files.push(...listFiles(base, next))
    else if (entry.isFile()) files.push(next.replaceAll('\\\\', '/'))
  }
  return files
}

function ensureReviewHtml() {
  const index = join(root, 'index.html')
  if (existsSync(index)) return

  const files = listFiles(root)
  const css = files.filter((item) => item.endsWith('.css')).sort()
  const js = files.filter((item) => item.endsWith('.js')).sort((a, b) => {
    const aApp = a.endsWith('/app.js') || a === 'app.js'
    const bApp = b.endsWith('/app.js') || b === 'app.js'
    if (aApp !== bApp) return aApp ? 1 : -1
    return a.localeCompare(b)
  })
  if (!js.some((item) => item.endsWith('/app.js') || item === 'app.js')) {
    throw new Error('H5 review bundle has no app.js entrypoint')
  }

  const html = [
    '<!doctype html>',
    '<html lang="zh-CN">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
    ...css.map((item) => '<link rel="stylesheet" href="/' + item + '">'),
    '</head>',
    '<body>',
    '<div id="app"></div>',
    ...js.map((item) => '<script src="/' + item + '"></script>'),
    '</body>',
    '</html>',
    '',
  ].join('\n')
  writeFileSync(index, html)
}

ensureReviewHtml()

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
}

const visualSession = {
  access_token: 'auth-006-visual-access-token',
  refresh_token: 'auth-006-visual-refresh-token',
  session_id: '22222222-2222-4222-8222-222222222222',
  token_type: 'bearer',
  user_id: '11111111-1111-4111-8111-111111111111',
  access_expires_at: '2099-01-01T00:00:00Z',
  refresh_expires_at: '2099-02-01T00:00:00Z',
  account_deletion_in_progress: false,
}

const visualIdentities = [
  {
    identity_id: '33333333-3333-4333-8333-333333333333',
    provider: 'EMAIL_PASSWORD',
    subject_hint: 'g***@example.test',
    verified_at: '2026-10-01T00:00:00Z',
    linked_at: '2026-10-01T00:00:00Z',
  },
  {
    identity_id: '44444444-4444-4444-8444-444444444444',
    provider: 'PHONE',
    subject_hint: '+86138****5678',
    verified_at: '2026-10-02T00:00:00Z',
    linked_at: '2026-10-02T00:00:00Z',
  },
]

const server = createServer((req, res) => {
  const raw = (req.url || '/').split('?')[0]
  let path = normalize(join(root, raw === '/' ? 'index.html' : raw))
  if (!path.startsWith(normalize(root))) {
    res.writeHead(403)
    res.end('forbidden')
    return
  }
  if (!existsSync(path) || statSync(path).isDirectory()) path = join(root, 'index.html')
  res.setHeader('Content-Type', mime[extname(path)] || 'application/octet-stream')
  createReadStream(path).pipe(res)
})

await new Promise((resolve) => server.listen(4173, '127.0.0.1', resolve))

const browser = await chromium.launch({ headless: true })
const manifest = []

try {
  for (const width of widths) {
    for (const scene of scenes) {
      const productionAccountSecurity = scene === 'account-security' || scene === 'account-security-empty'
      const emptyAccountSecurity = scene === 'account-security-empty'
      const page = await browser.newPage({
        viewport: { width, height },
        deviceScaleFactor: 1,
      })

      if (productionAccountSecurity) {
        await page.addInitScript((session) => {
          window.localStorage.setItem('jiyi_auth_session', JSON.stringify(session))
        }, visualSession)
        await page.route('https://api.example.invalid/v1/auth/identities', async (route) => {
          if (route.request().method() !== 'GET') {
            throw new Error('AUTH-006 visual page attempted a non-GET identity mutation')
          }
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ identities: emptyAccountSecurity ? [] : visualIdentities }),
          })
        })
      }

      const url = productionAccountSecurity
        ? 'http://127.0.0.1:4173/#/pages/account-security/index'
        : 'http://127.0.0.1:4173/#/pages/visual-review/index?scene=' + encodeURIComponent(scene)
      await page.goto(url, { waitUntil: 'networkidle' })
      await page.locator(productionAccountSecurity ? '.account-security-page' : '.visual-review')
        .waitFor({ state: 'visible' })
      await page.addStyleTag({
        content:
          '*{animation:none!important;transition:none!important;caret-color:transparent!important;}',
      })

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }))
      if (overflow.scrollWidth > overflow.clientWidth + 1) {
        throw new Error(
          scene + '@' + width + ': horizontal overflow ' +
          overflow.scrollWidth + ' > ' + overflow.clientWidth,
        )
      }

      if (productionAccountSecurity) {
        const accountPage = page.locator('.account-security-page')
        const text = await accountPage.innerText()
        if (!text.includes('账号与安全') || !text.includes('绑定与解绑')) {
          throw new Error(scene + '@' + width + ': production account-security page did not mount')
        }
        if (text.includes('golden@example.test')) {
          throw new Error(scene + '@' + width + ': unmasked identity leaked into visual fixture')
        }
        if (emptyAccountSecurity && !text.includes('当前没有可展示的登录身份。')) {
          throw new Error(scene + '@' + width + ': empty-state fixture did not render')
        }
        if (!emptyAccountSecurity && !text.includes('g***@example.test')) {
          throw new Error(scene + '@' + width + ': masked server identity did not render')
        }
      }

      const primaryActions = await page.locator('button').evaluateAll((nodes) =>
        nodes.map((node) => {
          const rect = node.getBoundingClientRect()
          return {
            text: node.textContent || '',
            left: rect.left,
            right: rect.right,
            width: rect.width,
          }
        }),
      )
      for (const action of primaryActions) {
        if (action.width < 44 || action.left < -1 || action.right > width + 1) {
          throw new Error(
            scene + '@' + width + ': clipped/tiny action ' + JSON.stringify(action),
          )
        }
      }

      const filename = scene + '-' + width + '.png'
      const path = join(out, filename)
      await page.screenshot({ path, fullPage: true })
      const bytes = readFileSync(path)
      manifest.push({
        scene,
        width,
        viewportHeight: height,
        sha256: createHash('sha256').update(bytes).digest('hex'),
      })
      await page.close()
    }
  }
} finally {
  await browser.close()
  await new Promise((resolve) => server.close(resolve))
}

writeFileSync(
  join(out, 'manifest.json'),
  JSON.stringify(
    {
      viewportWidths: widths,
      viewportHeight: height,
      scenes,
      screenshots: manifest,
    },
    null,
    2,
  ) + '\n',
)
