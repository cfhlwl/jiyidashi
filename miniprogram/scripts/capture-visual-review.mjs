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
      const page = await browser.newPage({
        viewport: { width, height },
        deviceScaleFactor: 1,
      })
      const url =
        'http://127.0.0.1:4173/#/pages/visual-review/index?scene=' +
        encodeURIComponent(scene)
      await page.goto(url, { waitUntil: 'networkidle' })
      await page.locator('.visual-review').waitFor({ state: 'visible' })
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
