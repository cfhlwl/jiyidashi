# Intent Router Foundation

## Purpose

S3-003 chooses which **existing trusted product capability** should receive a user
request. It is control metadata only: it does not answer the question, create facts,
write Memory/Evidence, or call an LLM/provider.

Public entry point:

`POST /v1/intent/route`

The authenticated server context supplies the owner. The request body contains only
the user's question and cannot select another user.

## Typed contract

| Intent | Capability | Existing trusted path |
| --- | --- | --- |
| `FIND_OBJECT` | `OBJECT_LOCATION_QUERY` | structured Object current-location lookup already used by `/v1/memory/query` |
| `FIND_PLACE` | `PLACE_HISTORY_QUERY` | existing Place/Visit APIs under `/v1/location/places` |
| `FIND_EVENT` | `MEMORY_QUERY` | existing evidence-gated `/v1/memory/query` |
| `MEMORY_SEARCH` | `MEMORY_QUERY` | existing evidence-gated `/v1/memory/query` |
| `UNKNOWN` | none | no automatic fallback |

## Deterministic precedence

1. Requests asking for unsupported mutations or reminder creation fail closed to
   `UNKNOWN / UNSUPPORTED`.
2. Known Object/Place names are matched only inside the authenticated owner's
   inventory. Longest unique names are accepted; equal best matches are ambiguous.
3. A request that simultaneously asks for specific Object and Place capabilities is
   `UNKNOWN / AMBIGUOUS`; this foundation does not split multi-intent requests.
4. A unique known Object plus an explicit location phrase routes to `FIND_OBJECT`.
5. Place/visit/footprint language routes to `FIND_PLACE`. This is more specific
   than generic event-time language, so “我什么时候去过公司” stays on Place/Visit.
6. Explicit event-time language routes to `FIND_EVENT`.
7. Explicit memory-search/recall language routes to `MEMORY_SEARCH`.
8. Weak, unsupported, or otherwise unclassified free text returns
   `UNKNOWN / NO_SUPPORTED_RULE`.

Generic memory-search words never override a more specific trusted route.

## Trust boundaries

- deterministic/rule-based only;
- no AI Gateway or model-provider import/call;
- no Memory/Evidence persistence and no schema migration;
- no automatic entity creation or entity linking;
- no request-body user identity;
- no reminder creation;
- no embeddings/vector/RAG;
- no fallback that guesses when rules are insufficient.

The existing Evidence gate remains owned by the downstream query services. The
router never upgrades a routing decision into evidence or a personal fact.
