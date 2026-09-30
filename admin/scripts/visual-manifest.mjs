import { createHash } from 'node:crypto'
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../visual-artifacts', import.meta.url))
await mkdir(root, { recursive: true })
const files = (await readdir(root)).filter((name) => name.endsWith('.png')).sort()
if (files.length < 10) {
  throw new Error(`expected at least 10 deterministic Admin screenshots, got ${files.length}`)
}
const entries = []
for (const name of files) {
  const bytes = await readFile(join(root, name))
  entries.push({
    file: name,
    bytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  })
}
await writeFile(
  join(root, 'manifest.json'),
  JSON.stringify({ version: 1, screenshots: entries }, null, 2) + '\n',
)
console.log(`Admin visual manifest PASS: ${entries.length} screenshots`)
