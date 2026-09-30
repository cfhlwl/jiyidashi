import { readdir, readFile } from 'node:fs/promises'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const root = fileURLToPath(new URL('../src', import.meta.url))
const visibleProps = new Set([
  'title',
  'description',
  'label',
  'message',
  'placeholder',
  'confirmText',
  'emptyText',
  'help_text',
  'eyebrow',
])
const forbidden = [
  /\bUUID\b/i,
  /\benum\b/i,
  /\bpayload\b/i,
  /\bcursor\b/i,
  /\brevision\b/i,
  /\btraceback\b/i,
  /\bstack trace\b/i,
  /\bprovider\b/i,
  /\bbackend\b/i,
  /\braw JSON\b/i,
  /\bmigration head\b/i,
  /\bHTTP\s+(?:422|500)\b/i,
  /\bPydantic\b/i,
  /\bPostgreSQL exception\b/i,
  /\binternal error code\b/i,
  /\brequest_id\b/i,
  /\buser_id\b/i,
  /\bfamily_id\b/i,
  /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){2,}\b/,
]

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

function nodeName(node) {
  if (ts.isIdentifier(node)) return node.text
  if (ts.isPropertyAccessExpression(node)) return node.name.text
  return ''
}

function stringsInside(node) {
  const values = []
  const visit = (child) => {
    if (
      ts.isStringLiteral(child) ||
      ts.isNoSubstitutionTemplateLiteral(child)
    ) {
      const value = child.text.replace(/\s+/g, ' ').trim()
      if (value) values.push(value)
      return
    }
    ts.forEachChild(child, visit)
  }
  visit(node)
  return values
}

function visibleSinks(source, fileName) {
  const kind = fileName.endsWith('.tsx')
    ? ts.ScriptKind.TSX
    : ts.ScriptKind.TS
  const tree = ts.createSourceFile(
    fileName,
    source,
    ts.ScriptTarget.Latest,
    true,
    kind,
  )
  const sinks = []

  const visit = (node) => {
    if (
      (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) &&
      nodeName(
        ts.isJsxElement(node)
          ? node.openingElement.tagName
          : node.tagName,
      ) === 'TechnicalDetails'
    ) {
      return
    }

    if (ts.isJsxText(node)) {
      const value = node.text.replace(/\s+/g, ' ').trim()
      if (value) sinks.push(value)
    }

    if (ts.isJsxAttribute(node)) {
      const name = node.name.getText(tree)
      if (visibleProps.has(name) && node.initializer) {
        if (ts.isStringLiteral(node.initializer)) {
          const value = node.initializer.text.trim()
          if (value) sinks.push(value)
        } else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
          sinks.push(...stringsInside(node.initializer.expression))
        }
      }
    }

    if (ts.isPropertyAssignment(node)) {
      const name = node.name.getText(tree).replace(/^['"]|['"]$/g, '')
      if (visibleProps.has(name)) {
        sinks.push(...stringsInside(node.initializer))
      } else if (fileName.endsWith('productLanguage.ts')) {
        sinks.push(...stringsInside(node.initializer))
      }
    }

    ts.forEachChild(node, visit)
  }

  visit(tree)
  return sinks
}

const violations = []
let sinkCount = 0
for (const file of await walk(root)) {
  const source = await readFile(file, 'utf8')
  const name = relative(root, file).replaceAll('\\', '/')
  for (const sink of visibleSinks(source, name)) {
    sinkCount += 1
    for (const pattern of forbidden) {
      if (pattern.test(sink)) {
        violations.push(`${name}: "${sink}"`)
        break
      }
    }
  }
}

if (sinkCount < 100) {
  console.error(
    `Admin Product Language Gate scan scope too small: ${sinkCount} visible sinks`,
  )
  process.exit(1)
}
if (violations.length) {
  console.error(
    'Admin Product Language Gate found developer-language leakage:',
  )
  console.error(violations.join('\n'))
  process.exit(1)
}

console.log(
  `Admin Product Language Gate PASS: ${sinkCount} visible sinks`,
)
