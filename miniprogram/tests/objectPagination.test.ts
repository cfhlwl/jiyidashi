import assert from 'node:assert/strict'
import test from 'node:test'

import {
  findUserObjectByNamePaginated,
  parseUserObjectPage,
} from '../src/services/objectPagination'

test('object pagination finds a target that exists only on page 2', async () => {
  const seen: Array<string | null> = []
  const found = await findUserObjectByNamePaginated(' 护照 ', async (cursor) => {
    seen.push(cursor)
    if (cursor === null) {
      return {
        items: [{ id: 'object-1', name: '钥匙' }],
        next_cursor: 'page-2',
      }
    }
    assert.equal(cursor, 'page-2')
    return {
      items: [{ id: 'object-2', name: '护照' }],
      next_cursor: null,
    }
  })

  assert.deepEqual(seen, [null, 'page-2'])
  assert.deepEqual(found, { id: 'object-2', name: '护照' })
})

test('object pagination exhausts every page before reporting not found', async () => {
  const found = await findUserObjectByNamePaginated('不存在', async (cursor) => {
    if (cursor === null) {
      return {
        items: [{ id: 'object-1', name: '钥匙' }],
        next_cursor: 'page-2',
      }
    }
    return {
      items: [{ id: 'object-2', name: '护照' }],
      next_cursor: null,
    }
  })
  assert.equal(found, null)
})

test('object pagination rejects malformed or looping cursors', async () => {
  assert.throws(
    () => parseUserObjectPage([{ id: 'legacy-array', name: '旧协议' }]),
    /服务端返回格式不正确/,
  )

  await assert.rejects(
    findUserObjectByNamePaginated('护照', async () => ({
      items: [],
      next_cursor: 'repeat',
    })),
    /服务端返回格式不正确/,
  )
})
