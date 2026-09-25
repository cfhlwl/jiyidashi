# Family Privacy Audit V1

Stage 4E / S4-015 defines a metadata-only audit trail for sensitive Family reads.

## Scope

V1 records these actions:

- `READ_CURRENT_LOCATION` / `VIEW_CURRENT_LOCATION`
- `READ_TODAY_FOOTPRINT` / `VIEW_FOOTPRINT`
- `READ_MEMORY` / `VIEW_MEMORY`
- `LIST_PHOTOS` / `VIEW_PHOTOS`
- `DOWNLOAD_PHOTO` / `VIEW_PHOTOS`

The authoritative direction is always:

`actor_user_id` = authenticated reader, and
`resource_owner_user_id` = owner of the sensitive data.

## Privacy boundary

An audit row contains access metadata only. It must never contain coordinates,
Place or Visit contents, Memory text/metadata, media object keys, photo or signed
URLs, storage headers, OCR/Vision output, EXIF, or raw backend/provider errors.

## Outcome semantics

- `ALLOWED`: the authorized projection/signing operation completed and the audit
  row committed in the same authoritative transaction.
- `DENIED`: both users are still in the same Family but the exact permission grant
  is absent. Cross-Family/non-member attempts are denied without creating a
  Family-scoped row, avoiding a new membership side channel.
- `UNAVAILABLE`: the exact grant exists, but the authorized resource cannot be
  disclosed (for example paused/stale/missing current location or unavailable photo).

The canonical membership pair lock and exact-grant lock remain the authorization
authority. Audit never replaces or duplicates permission resolution.

## Owner history API

`GET /v1/family/audit?limit=50`

- OWNER only; MEMBER receives `403 OWNER_REQUIRED`.
- Default history window is the recent 30 days.
- Limit is 1..50.
- Ordering is deterministic: `created_at DESC, event_id DESC`.
- Public projection is restricted to event id, actor/resource-owner ids, permission,
  resource category, action, result, and timestamp.

## Retention and deletion lifecycle

Server retention contract for V1 is **90 days**. The public API exposes only the
recent 30-day bounded window. A deployment maintenance job may delete audit events
older than 90 days; this is independent of ordinary Memory/photo deletion.

Ordinary Memory deletion, media deletion, or content edits do **not** delete the
corresponding Family audit metadata.

Account deletion is deliberately different: audit rows reference both actor and
resource owner with `ON DELETE CASCADE`, so deleting either user removes rows that
would otherwise retain a deleted account identifier. Deleting a Family likewise
removes its audit rows. Data Delete that preserves the User/Family identity does not
implicitly clear this privacy audit trail.

## Mini Program

The Family page exposes `隐私访问记录` only to OWNER. It is never fetched during
Family tab refresh; the user must explicitly tap the entry. Runtime parsing rejects
unknown enum values, malformed UUID/timestamps, duplicate event ids, pages over 50,
and unstable ordering.
