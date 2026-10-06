export type UserObject = {
  id: string
  name: string
}

export type UserObjectPage = {
  items: UserObject[]
  next_cursor: string | null
}

export function parseUserObjectPage(raw: unknown): UserObjectPage {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('服务端返回格式不正确')
  }
  const page = raw as { items?: unknown; next_cursor?: unknown }
  if (!Array.isArray(page.items)) throw new Error('服务端返回格式不正确')
  if (page.next_cursor !== null && typeof page.next_cursor !== 'string') {
    throw new Error('服务端返回格式不正确')
  }
  const items = page.items.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error('服务端返回格式不正确')
    }
    const candidate = item as { id?: unknown; name?: unknown }
    if (
      typeof candidate.id !== 'string' ||
      !candidate.id.trim() ||
      typeof candidate.name !== 'string'
    ) {
      throw new Error('服务端返回格式不正确')
    }
    return { id: candidate.id, name: candidate.name }
  })
  return { items, next_cursor: page.next_cursor as string | null }
}

export async function findUserObjectByNamePaginated(
  objectName: string,
  fetchPage: (cursor: string | null) => Promise<unknown>,
): Promise<UserObject | null> {
  const normalized = objectName.trim().toLocaleLowerCase()
  let cursor: string | null = null
  const seenCursors = new Set<string>()

  while (true) {
    const page = parseUserObjectPage(await fetchPage(cursor))
    const matched = page.items.find(
      (item) => item.name.trim().toLocaleLowerCase() === normalized,
    )
    if (matched) return matched
    if (page.next_cursor === null) return null
    const next = page.next_cursor.trim()
    if (!next || seenCursors.has(next)) throw new Error('服务端返回格式不正确')
    seenCursors.add(next)
    cursor = next
  }
}
