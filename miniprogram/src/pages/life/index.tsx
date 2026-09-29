import Taro, { useDidHide, useDidShow } from '@tarojs/taro'
import { Button, Input, Picker, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  createLifeEvent,
  createLifeStage,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  currentElderModeEnabled,
  deleteLifeEvent,
  deleteLifeStage,
  generateAnnualMemoir,
  generateLifeMemoirChapter,
  getAnnualMemoirPhotos,
  getLifeEvent,
  getLifeHistory,
  getLifeMemoirStages,
  getLifeStage,
  getVerifiedMediaDownload,
  isAuthenticated,
  linkLifeEventMemory,
  linkLifeStageEvent,
  listLifeEventMemories,
  listLifeEvents,
  listLifeStageEvents,
  listLifeStages,
  listMemoryPickerRows,
  listPlaces,
  patchLifeEvent,
  patchLifeStage,
  reasonAboutLifeStage,
  subscribeAuthSession,
  subscribeElderMode,
  unlinkLifeEventMemory,
  unlinkLifeStageEvent,
  type AnnualMemoir,
  type LifeEventMemoryEvidence,
  type LifeEventRead,
  type LifeHistoryPage,
  type LifeMemoirChapter,
  type LifeMemoirStageIndexPage,
  type LifeStageEventEvidence,
  type LifeStageRead,
  type LongTermReasoningResult,
  type MemoryRead,
} from '../../services/api'
import {
  AdvancedV2Authority,
  AdvancedV2SingleFlight,
  LIFE_EVENT_KINDS,
  LIFE_STAGE_KINDS,
  annualNarrativePresentation,
  lifeMemoirPresentation,
  reasoningPresentation,
  type LifeEventCreatePayload,
  type LifeEventKind,
  type LifeStageCreatePayload,
  type LifeStageKind,
} from '../../services/advancedV2'
import { elderClassName } from '../../services/elderMode'
import type { PlaceRead } from '../../services/placeDetail'
import './index.scss'

type Section = 'home' | 'events' | 'stages' | 'history' | 'memoirs'
type FormMode = 'none' | 'create' | 'edit'

type EventDraft = {
  eventKind: LifeEventKind
  title: string
  customLabel: string
  note: string
  startedAt: string
  endedAt: string
  placeId: string
}

type StageDraft = {
  stageKind: LifeStageKind
  title: string
  customLabel: string
  note: string
  startedAt: string
  endedAt: string
}

const AWARE_RE = /(Z|[+-][0-9]{2}:[0-9]{2})$/
const EVENT_LABELS: Record<LifeEventKind, string> = {
  TRAVEL: '旅行',
  MEDICAL: '医疗',
  GATHERING: '聚会',
  WORK: '工作',
  EDUCATION: '学习',
  FAMILY: '家庭',
  OTHER: '其他',
}
const STAGE_LABELS: Record<LifeStageKind, string> = {
  WORK: '工作',
  EDUCATION: '学习',
  FAMILY: '家庭',
  RESIDENCE: '居住',
  TRAVEL: '旅行',
  OTHER: '其他',
}

function nowIso(): string {
  return new Date().toISOString()
}

function blankEventDraft(): EventDraft {
  return {
    eventKind: 'WORK',
    title: '',
    customLabel: '',
    note: '',
    startedAt: nowIso(),
    endedAt: '',
    placeId: '',
  }
}

function blankStageDraft(): StageDraft {
  return {
    stageKind: 'WORK',
    title: '',
    customLabel: '',
    note: '',
    startedAt: nowIso(),
    endedAt: '',
  }
}

function eventDraftFrom(value: LifeEventRead): EventDraft {
  return {
    eventKind: value.event_kind,
    title: value.title,
    customLabel: value.custom_label || '',
    note: value.note || '',
    startedAt: value.started_at,
    endedAt: value.ended_at || '',
    placeId: value.place_id || '',
  }
}

function stageDraftFrom(value: LifeStageRead): StageDraft {
  return {
    stageKind: value.stage_kind,
    title: value.title,
    customLabel: value.custom_label || '',
    note: value.note || '',
    startedAt: value.started_at,
    endedAt: value.ended_at || '',
  }
}

function requiredAware(value: string, label: string): string {
  const next = value.trim()
  if (!AWARE_RE.test(next) || !Number.isFinite(Date.parse(next))) {
    throw new Error(label + '必须是带时区的 ISO 时间')
  }
  return next
}

function optionalAware(value: string, label: string): string | null {
  const next = value.trim()
  if (!next) return null
  return requiredAware(next, label)
}

function eventPayload(draft: EventDraft): LifeEventCreatePayload {
  const title = draft.title.trim()
  if (!title || title.length > 240) throw new Error('事件标题需为 1–240 个字符')
  const custom = draft.customLabel.trim()
  if (draft.eventKind === 'OTHER' && !custom) throw new Error('“其他”事件需要填写自定义类型')
  if (draft.eventKind !== 'OTHER' && custom) throw new Error('只有“其他”事件可以填写自定义类型')
  const started = requiredAware(draft.startedAt, '开始时间')
  const ended = optionalAware(draft.endedAt, '结束时间')
  if (ended && Date.parse(ended) < Date.parse(started)) throw new Error('结束时间不能早于开始时间')
  const note = draft.note.trim()
  if (note.length > 5000) throw new Error('备注不能超过 5000 个字符')
  return {
    event_kind: draft.eventKind,
    title,
    custom_label: draft.eventKind === 'OTHER' ? custom : null,
    note: note || null,
    started_at: started,
    ended_at: ended,
    place_id: draft.placeId || null,
  }
}

function stagePayload(draft: StageDraft): LifeStageCreatePayload {
  const title = draft.title.trim()
  if (!title || title.length > 240) throw new Error('阶段标题需为 1–240 个字符')
  const custom = draft.customLabel.trim()
  if (draft.stageKind === 'OTHER' && !custom) throw new Error('“其他”阶段需要填写自定义类型')
  if (draft.stageKind !== 'OTHER' && custom) throw new Error('只有“其他”阶段可以填写自定义类型')
  const started = requiredAware(draft.startedAt, '开始时间')
  const ended = optionalAware(draft.endedAt, '结束时间')
  if (ended && Date.parse(ended) < Date.parse(started)) throw new Error('结束时间不能早于开始时间')
  const note = draft.note.trim()
  if (note.length > 5000) throw new Error('备注不能超过 5000 个字符')
  return {
    stage_kind: draft.stageKind,
    title,
    custom_label: draft.stageKind === 'OTHER' ? custom : null,
    note: note || null,
    started_at: started,
    ended_at: ended,
  }
}

function mutationError(error: unknown, fallback: string): string {
  const code = apiErrorCode(error)
  if (code) return fallback + '（' + code + '）'
  return error instanceof Error ? error.message : fallback
}

function shortId(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 8) + '…' + value.slice(-4) : value
}

export default function Page() {
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const [section, setSection] = useState<Section>('home')
  const [globalStatus, setGlobalStatus] = useState('')

  const eventListAuthority = useRef(new AdvancedV2Authority())
  const eventDetailAuthority = useRef(new AdvancedV2Authority())
  const stageListAuthority = useRef(new AdvancedV2Authority())
  const stageDetailAuthority = useRef(new AdvancedV2Authority())
  const reasoningAuthority = useRef(new AdvancedV2Authority())
  const historyAuthority = useRef(new AdvancedV2Authority())
  const annualAuthority = useRef(new AdvancedV2Authority())
  const annualTimelineAuthority = useRef(new AdvancedV2Authority())
  const annualPhotoAuthority = useRef(new AdvancedV2Authority())
  const memoirIndexAuthority = useRef(new AdvancedV2Authority())
  const memoirChapterAuthority = useRef(new AdvancedV2Authority())
  const mutationAuthority = useRef(new AdvancedV2Authority())

  const mutationGate = useRef(new AdvancedV2SingleFlight())
  const reasoningGate = useRef(new AdvancedV2SingleFlight())
  const annualGate = useRef(new AdvancedV2SingleFlight())
  const chapterGate = useRef(new AdvancedV2SingleFlight())

  const [events, setEvents] = useState<LifeEventRead[]>([])
  const [eventsLoading, setEventsLoading] = useState(false)
  const [eventStatus, setEventStatus] = useState('')
  const [selectedEvent, setSelectedEvent] = useState<LifeEventRead | null>(null)
  const [eventEvidence, setEventEvidence] = useState<LifeEventMemoryEvidence[]>([])
  const [memoryChoices, setMemoryChoices] = useState<MemoryRead[]>([])
  const [placeChoices, setPlaceChoices] = useState<PlaceRead[]>([])
  const [memoryChoiceIndex, setMemoryChoiceIndex] = useState(0)
  const [eventFormMode, setEventFormMode] = useState<FormMode>('none')
  const [eventDraft, setEventDraft] = useState<EventDraft>(blankEventDraft)

  const [stages, setStages] = useState<LifeStageRead[]>([])
  const [stagesLoading, setStagesLoading] = useState(false)
  const [stageStatus, setStageStatus] = useState('')
  const [selectedStage, setSelectedStage] = useState<LifeStageRead | null>(null)
  const [stageEvidence, setStageEvidence] = useState<LifeStageEventEvidence[]>([])
  const [eventChoiceIndex, setEventChoiceIndex] = useState(0)
  const [stageFormMode, setStageFormMode] = useState<FormMode>('none')
  const [stageDraft, setStageDraft] = useState<StageDraft>(blankStageDraft)
  const [reasonQuestion, setReasonQuestion] = useState('')
  const [reasoning, setReasoning] = useState<LongTermReasoningResult | null>(null)
  const [reasoningLoading, setReasoningLoading] = useState(false)

  const thisYear = new Date().getUTCFullYear()
  const [historyStart, setHistoryStart] = useState(String(Math.max(1, thisYear - 5)))
  const [historyEnd, setHistoryEnd] = useState(String(thisYear))
  const [history, setHistory] = useState<LifeHistoryPage | null>(null)
  const [historyItems, setHistoryItems] = useState<LifeHistoryPage['items']>([])
  const [historyCursor, setHistoryCursor] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyStatus, setHistoryStatus] = useState('')

  const [annualYear, setAnnualYear] = useState(String(Math.max(1, thisYear - 1)).padStart(4, '0'))
  const [annual, setAnnual] = useState<AnnualMemoir | null>(null)
  const [annualTimelineItems, setAnnualTimelineItems] = useState<LifeHistoryPage['items']>([])
  const [annualTimelineCursor, setAnnualTimelineCursor] = useState<string | null>(null)
  const [annualPhotos, setAnnualPhotos] = useState<AnnualMemoir['photo_items']>([])
  const [annualPhotoCursor, setAnnualPhotoCursor] = useState<string | null>(null)
  const [annualLoading, setAnnualLoading] = useState(false)
  const [annualStatus, setAnnualStatus] = useState('')

  const [memoirIndex, setMemoirIndex] = useState<LifeMemoirStageIndexPage['items']>([])
  const [memoirCursor, setMemoirCursor] = useState<string | null>(null)
  const [memoirIndexLoading, setMemoirIndexLoading] = useState(false)
  const [selectedMemoirStageId, setSelectedMemoirStageId] = useState('')
  const [chapter, setChapter] = useState<LifeMemoirChapter | null>(null)
  const [chapterLoading, setChapterLoading] = useState(false)
  const [memoirStatus, setMemoirStatus] = useState('')

  const [mutating, setMutating] = useState(false)

  const authorities = [
    eventListAuthority,
    eventDetailAuthority,
    stageListAuthority,
    stageDetailAuthority,
    reasoningAuthority,
    historyAuthority,
    annualAuthority,
    annualTimelineAuthority,
    annualPhotoAuthority,
    memoirIndexAuthority,
    memoirChapterAuthority,
    mutationAuthority,
  ]

  const invalidateAll = () => {
    authorities.forEach((item) => item.current.invalidate())
  }

  const resetOwnerState = () => {
    setEvents([])
    setSelectedEvent(null)
    setEventEvidence([])
    setMemoryChoices([])
    setPlaceChoices([])
    setStages([])
    setSelectedStage(null)
    setStageEvidence([])
    setReasoning(null)
    setHistory(null)
    setHistoryItems([])
    setHistoryCursor(null)
    setAnnual(null)
    setAnnualTimelineItems([])
    setAnnualTimelineCursor(null)
    setAnnualPhotos([])
    setAnnualPhotoCursor(null)
    setMemoirIndex([])
    setMemoirCursor(null)
    setSelectedMemoirStageId('')
    setChapter(null)
    setGlobalStatus('')
    setEventStatus('')
    setStageStatus('')
    setHistoryStatus('')
    setAnnualStatus('')
    setMemoirStatus('')
    setEventsLoading(false)
    setStagesLoading(false)
    setReasoningLoading(false)
    setHistoryLoading(false)
    setAnnualLoading(false)
    setMemoirIndexLoading(false)
    setChapterLoading(false)
    setMutating(false)
  }

  const capture = (authority: AdvancedV2Authority, identity: string) => {
    const owner = currentAuthenticatedUserId()
    if (!owner || !isAuthenticated()) throw new Error('请先登录')
    return authority.capture(owner, currentAuthSessionEpoch(), identity)
  }

  const isCurrent = (
    authority: AdvancedV2Authority,
    snapshot: ReturnType<AdvancedV2Authority['capture']>,
  ) => authority.isCurrent(
    snapshot,
    currentAuthenticatedUserId(),
    currentAuthSessionEpoch(),
    snapshot.identity,
  )

  useEffect(() => subscribeElderMode(setElderMode), [])

  useEffect(() => subscribeAuthSession(() => {
    invalidateAll()
    resetOwnerState()
  }), [])

  useEffect(() => () => invalidateAll(), [])

  useDidHide(() => {
    invalidateAll()
    setEventsLoading(false)
    setStagesLoading(false)
    setReasoningLoading(false)
    setHistoryLoading(false)
    setAnnualLoading(false)
    setMemoirIndexLoading(false)
    setChapterLoading(false)
  })

  const loadEvents = async () => {
    if (!isAuthenticated()) return
    let snapshot
    try {
      snapshot = capture(eventListAuthority.current, 'events:list')
    } catch {
      return
    }
    setEventsLoading(true)
    setEventStatus('')
    try {
      const rows = await listLifeEvents(100)
      if (!isCurrent(eventListAuthority.current, snapshot)) return
      setEvents(rows)
    } catch (error) {
      if (!isCurrent(eventListAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, '人生事件加载失败'))
    } finally {
      if (isCurrent(eventListAuthority.current, snapshot)) setEventsLoading(false)
    }
  }

  const loadStages = async () => {
    if (!isAuthenticated()) return
    let snapshot
    try {
      snapshot = capture(stageListAuthority.current, 'stages:list')
    } catch {
      return
    }
    setStagesLoading(true)
    setStageStatus('')
    try {
      const rows = await listLifeStages(100)
      if (!isCurrent(stageListAuthority.current, snapshot)) return
      setStages(rows)
    } catch (error) {
      if (!isCurrent(stageListAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '人生阶段加载失败'))
    } finally {
      if (isCurrent(stageListAuthority.current, snapshot)) setStagesLoading(false)
    }
  }

  const loadEventDetail = async (eventId: string) => {
    eventDetailAuthority.current.invalidate()
    setSelectedEvent(null)
    setEventEvidence([])
    setMemoryChoices([])
    setMemoryChoiceIndex(0)
    setEventFormMode('none')
    setEventStatus('')
    const owner = currentAuthenticatedUserId()
    if (!owner) return
    let snapshot
    try {
      snapshot = capture(eventDetailAuthority.current, 'event:' + eventId)
    } catch {
      return
    }
    try {
      const [detail, evidence, memories, places] = await Promise.all([
        getLifeEvent(eventId),
        listLifeEventMemories(eventId, 100),
        listMemoryPickerRows(owner, 50),
        listPlaces(100),
      ])
      if (!isCurrent(eventDetailAuthority.current, snapshot)) return
      setSelectedEvent(detail)
      setEventEvidence(evidence)
      setMemoryChoices(memories.filter((memory) => memory.source_type !== 'AI_INFERENCE'))
      setPlaceChoices(places)
    } catch (error) {
      if (!isCurrent(eventDetailAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, '事件详情加载失败'))
    }
  }

  const loadStageDetail = async (stageId: string) => {
    stageDetailAuthority.current.invalidate()
    reasoningAuthority.current.invalidate()
    setSelectedStage(null)
    setStageEvidence([])
    setStageFormMode('none')
    setReasoning(null)
    setReasonQuestion('')
    setStageStatus('')
    let snapshot
    try {
      snapshot = capture(stageDetailAuthority.current, 'stage:' + stageId)
    } catch {
      return
    }
    try {
      const [detail, evidence] = await Promise.all([
        getLifeStage(stageId),
        listLifeStageEvents(stageId, 100),
      ])
      if (!isCurrent(stageDetailAuthority.current, snapshot)) return
      setSelectedStage(detail)
      setStageEvidence(evidence)
    } catch (error) {
      if (!isCurrent(stageDetailAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '阶段详情加载失败'))
    }
  }

  const refreshOverview = () => {
    void loadEvents()
    void loadStages()
  }

  useDidShow(() => {
    if (isAuthenticated() && !elderMode) refreshOverview()
  })

  const openSection = (next: Section) => {
    setSection(next)
    setGlobalStatus('')
    if (next === 'events') void loadEvents()
    if (next === 'stages') void loadStages()
    if (next === 'memoirs' && memoirIndex.length === 0) void loadMemoirStages(false)
  }

  const beginMutation = (identity: string) => {
    if (!mutationGate.current.begin()) return null
    setMutating(true)
    try {
      return capture(mutationAuthority.current, identity)
    } catch (error) {
      mutationGate.current.end()
      setMutating(false)
      throw error
    }
  }

  const finishMutation = () => {
    mutationGate.current.end()
    setMutating(false)
  }

  const saveEvent = async () => {
    if (eventFormMode === 'none') return
    let payload: LifeEventCreatePayload
    try {
      payload = eventPayload(eventDraft)
    } catch (error) {
      setEventStatus(error instanceof Error ? error.message : '请检查事件内容')
      return
    }
    const target = eventFormMode === 'edit' ? selectedEvent : null
    const snapshot = beginMutation(target ? 'event:update:' + target.id : 'event:create')
    if (!snapshot) return
    eventListAuthority.current.invalidate()
    eventDetailAuthority.current.invalidate()
    setEventStatus('')
    try {
      const saved = target
        ? await patchLifeEvent(target.id, { ...payload, expected_revision: target.revision })
        : await createLifeEvent(payload)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventFormMode('none')
      setSelectedEvent(saved)
      setEventStatus(target ? '事件已更新' : '事件已创建')
      await loadEvents()
      await loadEventDetail(saved.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, target ? '事件更新失败' : '事件创建失败'))
    } finally {
      finishMutation()
    }
  }

  const confirmDeleteEvent = async () => {
    const target = selectedEvent
    if (!target || mutating) return
    const modal = await Taro.showModal({
      title: '删除人生事件？',
      content: '将删除“' + target.title + '”以及它的显式关联关系。',
      confirmText: '删除',
      confirmColor: '#b3261e',
    })
    if (!modal.confirm) return
    const snapshot = beginMutation('event:delete:' + target.id)
    if (!snapshot) return
    eventListAuthority.current.invalidate()
    eventDetailAuthority.current.invalidate()
    try {
      await deleteLifeEvent(target.id)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setSelectedEvent(null)
      setEventEvidence([])
      setEventStatus('事件已删除')
      await loadEvents()
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, '事件删除失败'))
    } finally {
      finishMutation()
    }
  }

  const availableMemories = memoryChoices.filter(
    (memory) => !eventEvidence.some((evidence) => evidence.memory_id === memory.id),
  )

  const linkSelectedMemory = async () => {
    const target = selectedEvent
    const memory = availableMemories[memoryChoiceIndex]
    if (!target || !memory) return
    const snapshot = beginMutation('event:link:' + target.id + ':' + memory.id)
    if (!snapshot) return
    eventDetailAuthority.current.invalidate()
    try {
      await linkLifeEventMemory(target.id, memory.id)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setMemoryChoiceIndex(0)
      setEventStatus('记忆证据已关联')
      await loadEventDetail(target.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, '记忆关联失败'))
    } finally {
      finishMutation()
    }
  }

  const unlinkMemory = async (memoryId: string) => {
    const target = selectedEvent
    if (!target) return
    const modal = await Taro.showModal({
      title: '取消证据关联？',
      content: '只会删除事件与这条记忆的显式关联，不会删除记忆本身。',
      confirmText: '取消关联',
    })
    if (!modal.confirm) return
    const snapshot = beginMutation('event:unlink:' + target.id + ':' + memoryId)
    if (!snapshot) return
    eventDetailAuthority.current.invalidate()
    try {
      await unlinkLifeEventMemory(target.id, memoryId)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventStatus('记忆证据关联已取消')
      await loadEventDetail(target.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventStatus(mutationError(error, '取消关联失败'))
    } finally {
      finishMutation()
    }
  }

  const saveStage = async () => {
    if (stageFormMode === 'none') return
    let payload: LifeStageCreatePayload
    try {
      payload = stagePayload(stageDraft)
    } catch (error) {
      setStageStatus(error instanceof Error ? error.message : '请检查阶段内容')
      return
    }
    const target = stageFormMode === 'edit' ? selectedStage : null
    const snapshot = beginMutation(target ? 'stage:update:' + target.id : 'stage:create')
    if (!snapshot) return
    stageListAuthority.current.invalidate()
    stageDetailAuthority.current.invalidate()
    reasoningAuthority.current.invalidate()
    setStageStatus('')
    try {
      const saved = target
        ? await patchLifeStage(target.id, { ...payload, expected_revision: target.revision })
        : await createLifeStage(payload)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setStageFormMode('none')
      setSelectedStage(saved)
      setStageStatus(target ? '阶段已更新' : '阶段已创建')
      await loadStages()
      await loadStageDetail(saved.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, target ? '阶段更新失败' : '阶段创建失败'))
    } finally {
      finishMutation()
    }
  }

  const confirmDeleteStage = async () => {
    const target = selectedStage
    if (!target || mutating) return
    const modal = await Taro.showModal({
      title: '删除人生阶段？',
      content: '将删除“' + target.title + '”以及它的事件关联。',
      confirmText: '删除',
      confirmColor: '#b3261e',
    })
    if (!modal.confirm) return
    const snapshot = beginMutation('stage:delete:' + target.id)
    if (!snapshot) return
    stageListAuthority.current.invalidate()
    stageDetailAuthority.current.invalidate()
    reasoningAuthority.current.invalidate()
    try {
      await deleteLifeStage(target.id)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setSelectedStage(null)
      setStageEvidence([])
      setReasoning(null)
      setStageStatus('阶段已删除')
      await loadStages()
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '阶段删除失败'))
    } finally {
      finishMutation()
    }
  }

  const availableEvents = events.filter(
    (event) => !stageEvidence.some((evidence) => evidence.life_event_id === event.id),
  )

  const linkSelectedEvent = async () => {
    const stage = selectedStage
    const event = availableEvents[eventChoiceIndex]
    if (!stage || !event) return
    const snapshot = beginMutation('stage:link:' + stage.id + ':' + event.id)
    if (!snapshot) return
    stageDetailAuthority.current.invalidate()
    reasoningAuthority.current.invalidate()
    try {
      await linkLifeStageEvent(stage.id, event.id)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setEventChoiceIndex(0)
      setReasoning(null)
      setStageStatus('事件已关联到阶段')
      await loadStageDetail(stage.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '事件关联失败'))
    } finally {
      finishMutation()
    }
  }

  const unlinkStageEvent = async (eventId: string) => {
    const stage = selectedStage
    if (!stage) return
    const modal = await Taro.showModal({
      title: '取消事件关联？',
      content: '只删除人生阶段与事件之间的显式关系。',
      confirmText: '取消关联',
    })
    if (!modal.confirm) return
    const snapshot = beginMutation('stage:unlink:' + stage.id + ':' + eventId)
    if (!snapshot) return
    stageDetailAuthority.current.invalidate()
    reasoningAuthority.current.invalidate()
    try {
      await unlinkLifeStageEvent(stage.id, eventId)
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setReasoning(null)
      setStageStatus('事件关联已取消')
      await loadStageDetail(stage.id)
    } catch (error) {
      if (!isCurrent(mutationAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '取消事件关联失败'))
    } finally {
      finishMutation()
    }
  }

  const generateReasoning = async () => {
    const stage = selectedStage
    const question = reasonQuestion.trim()
    if (!stage || !question || reasoningGate.current.isPending()) {
      if (!question) setStageStatus('请输入要回顾的问题')
      return
    }
    if (!reasoningGate.current.begin()) return
    reasoningAuthority.current.invalidate()
    const snapshot = capture(reasoningAuthority.current, 'reason:' + stage.id)
    setReasoningLoading(true)
    setReasoning(null)
    setStageStatus('')
    try {
      const result = await reasonAboutLifeStage(stage.id, question)
      if (!isCurrent(reasoningAuthority.current, snapshot)) return
      setReasoning(result)
    } catch (error) {
      if (!isCurrent(reasoningAuthority.current, snapshot)) return
      setStageStatus(mutationError(error, '长期回顾生成失败'))
    } finally {
      reasoningGate.current.end()
      if (isCurrent(reasoningAuthority.current, snapshot)) setReasoningLoading(false)
    }
  }

  const parseHistoryRange = () => {
    const start = Number(historyStart)
    const end = Number(historyEnd)
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end > 9998 || start > end) {
      throw new Error('年份范围无效')
    }
    return { start, end }
  }

  const loadHistory = async (append: boolean) => {
    let range
    try {
      range = parseHistoryRange()
    } catch (error) {
      setHistoryStatus(error instanceof Error ? error.message : '年份范围无效')
      return
    }
    const nextCursor = append ? historyCursor : null
    if (append && !nextCursor) return
    historyAuthority.current.invalidate()
    const snapshot = capture(
      historyAuthority.current,
      'history:' + range.start + ':' + range.end + ':' + (nextCursor || 'root'),
    )
    setHistoryLoading(true)
    setHistoryStatus('')
    if (!append) {
      setHistory(null)
      setHistoryItems([])
      setHistoryCursor(null)
    }
    try {
      const page = await getLifeHistory(range.start, range.end, { limit: 50, cursor: nextCursor })
      if (!isCurrent(historyAuthority.current, snapshot)) return
      setHistory(page)
      setHistoryItems((current) => append ? [...current, ...page.items] : page.items)
      setHistoryCursor(page.next_cursor)
    } catch (error) {
      if (!isCurrent(historyAuthority.current, snapshot)) return
      setHistoryStatus(mutationError(error, '多年时间线加载失败'))
    } finally {
      if (isCurrent(historyAuthority.current, snapshot)) setHistoryLoading(false)
    }
  }

  const validateAnnualYear = () => {
    const value = annualYear.trim()
    if (!/^[0-9]{4}$/.test(value) || Number(value) < 1 || Number(value) > 9998) {
      throw new Error('年度必须是四位年份')
    }
    return value
  }

  const runAnnualMemoir = async () => {
    let year
    try {
      year = validateAnnualYear()
    } catch (error) {
      setAnnualStatus(error instanceof Error ? error.message : '年度无效')
      return
    }
    if (!annualGate.current.begin()) return
    annualAuthority.current.invalidate()
    annualTimelineAuthority.current.invalidate()
    annualPhotoAuthority.current.invalidate()
    const snapshot = capture(annualAuthority.current, 'annual:' + year)
    setAnnualLoading(true)
    setAnnualStatus('')
    setAnnual(null)
    setAnnualTimelineItems([])
    setAnnualTimelineCursor(null)
    setAnnualPhotos([])
    setAnnualPhotoCursor(null)
    try {
      const result = await generateAnnualMemoir(year)
      if (!isCurrent(annualAuthority.current, snapshot)) return
      setAnnual(result)
      setAnnualTimelineItems(result.timeline_items)
      setAnnualTimelineCursor(result.timeline_next_cursor)
      setAnnualPhotos(result.photo_items)
      setAnnualPhotoCursor(result.photo_next_cursor)
    } catch (error) {
      if (!isCurrent(annualAuthority.current, snapshot)) return
      setAnnualStatus(mutationError(error, '年度回忆录生成失败'))
    } finally {
      annualGate.current.end()
      if (isCurrent(annualAuthority.current, snapshot)) setAnnualLoading(false)
    }
  }

  const loadMoreAnnualTimeline = async () => {
    if (!annual || !annualTimelineCursor) return
    const year = Number(annual.target_year)
    annualTimelineAuthority.current.invalidate()
    const snapshot = capture(
      annualTimelineAuthority.current,
      'annual-timeline:' + annual.target_year + ':' + annualTimelineCursor,
    )
    try {
      const page = await getLifeHistory(year, year, { limit: 50, cursor: annualTimelineCursor })
      if (!isCurrent(annualTimelineAuthority.current, snapshot)) return
      setAnnualTimelineItems((current) => [...current, ...page.items])
      setAnnualTimelineCursor(page.next_cursor)
    } catch (error) {
      if (!isCurrent(annualTimelineAuthority.current, snapshot)) return
      setAnnualStatus(mutationError(error, '年度时间线继续加载失败'))
    }
  }

  const previewAnnualPhoto = async (mediaId: string) => {
    annualPhotoAuthority.current.invalidate()
    const snapshot = capture(annualPhotoAuthority.current, 'annual-photo-preview:' + mediaId)
    setAnnualStatus('')
    try {
      const signed = await getVerifiedMediaDownload(mediaId)
      if (!isCurrent(annualPhotoAuthority.current, snapshot)) return
      await Taro.previewImage({
        current: signed.download.url,
        urls: [signed.download.url],
      })
    } catch (error) {
      if (!isCurrent(annualPhotoAuthority.current, snapshot)) return
      setAnnualStatus(mutationError(error, '照片打开失败'))
    }
  }

  const loadMoreAnnualPhotos = async () => {
    if (!annual || !annualPhotoCursor) return
    annualPhotoAuthority.current.invalidate()
    const snapshot = capture(
      annualPhotoAuthority.current,
      'annual-photos:' + annual.target_year + ':' + annualPhotoCursor,
    )
    try {
      const page = await getAnnualMemoirPhotos(annual.target_year, { limit: 24, cursor: annualPhotoCursor })
      if (!isCurrent(annualPhotoAuthority.current, snapshot)) return
      setAnnualPhotos((current) => [...current, ...page.items])
      setAnnualPhotoCursor(page.next_cursor)
    } catch (error) {
      if (!isCurrent(annualPhotoAuthority.current, snapshot)) return
      setAnnualStatus(mutationError(error, '年度照片继续加载失败'))
    }
  }

  async function loadMemoirStages(append: boolean) {
    const nextCursor = append ? memoirCursor : null
    if (append && !nextCursor) return
    memoirIndexAuthority.current.invalidate()
    const snapshot = capture(
      memoirIndexAuthority.current,
      'memoir-index:' + (nextCursor || 'root'),
    )
    setMemoirIndexLoading(true)
    setMemoirStatus('')
    if (!append) {
      setMemoirIndex([])
      setMemoirCursor(null)
    }
    try {
      const page = await getLifeMemoirStages({ limit: 50, cursor: nextCursor })
      if (!isCurrent(memoirIndexAuthority.current, snapshot)) return
      setMemoirIndex((current) => append ? [...current, ...page.items] : page.items)
      setMemoirCursor(page.next_cursor)
    } catch (error) {
      if (!isCurrent(memoirIndexAuthority.current, snapshot)) return
      setMemoirStatus(mutationError(error, '人生回忆录阶段加载失败'))
    } finally {
      if (isCurrent(memoirIndexAuthority.current, snapshot)) setMemoirIndexLoading(false)
    }
  }

  const selectMemoirStage = (stageId: string) => {
    memoirChapterAuthority.current.invalidate()
    setSelectedMemoirStageId(stageId)
    setChapter(null)
    setMemoirStatus('')
  }

  const generateChapter = async () => {
    const stageId = selectedMemoirStageId
    if (!stageId || !chapterGate.current.begin()) return
    memoirChapterAuthority.current.invalidate()
    const snapshot = capture(memoirChapterAuthority.current, 'chapter:' + stageId)
    setChapterLoading(true)
    setChapter(null)
    setMemoirStatus('')
    try {
      const result = await generateLifeMemoirChapter(stageId)
      if (!isCurrent(memoirChapterAuthority.current, snapshot)) return
      setChapter(result)
    } catch (error) {
      if (!isCurrent(memoirChapterAuthority.current, snapshot)) return
      setMemoirStatus(mutationError(error, '人生回忆录章节生成失败'))
    } finally {
      chapterGate.current.end()
      if (isCurrent(memoirChapterAuthority.current, snapshot)) setChapterLoading(false)
    }
  }

  const changeAnnualYear = (value: string) => {
    annualAuthority.current.invalidate()
    annualTimelineAuthority.current.invalidate()
    annualPhotoAuthority.current.invalidate()
    setAnnualYear(value)
    setAnnual(null)
    setAnnualTimelineItems([])
    setAnnualTimelineCursor(null)
    setAnnualPhotos([])
    setAnnualPhotoCursor(null)
    setAnnualStatus('')
  }

  if (!isAuthenticated()) {
    return (
      <View>
        <View className='title'>人生</View>
        <View className='card'>
          <View className='card-title'>请先登录</View>
          <Text className='muted'>登录后才能查看和维护你的人生事件、阶段与回忆录。</Text>
        </View>
      </View>
    )
  }

  if (elderMode) {
    return (
      <View className={elderClassName(true)}>
        <View className='title'>人生</View>
        <View className='card'>
          <View className='card-title'>高级人生整理</View>
          <Text className='muted'>长辈模式保持常用功能简洁；高级事件、阶段和回忆录编辑请在普通模式使用。</Text>
        </View>
      </View>
    )
  }

  const reasonPresentation = reasoning ? reasoningPresentation(reasoning.status) : null
  const annualPresentation = annual ? annualNarrativePresentation(annual.narrative_status) : null
  const chapterPresentation = chapter ? lifeMemoirPresentation(chapter) : null

  return (
    <View>
      <View className='title'>人生</View>
      <View className='subtitle'>把明确记录整理成人生事件和阶段；只有标明的 AI 回顾会调用生成能力。</View>

      {section !== 'home' && (
        <Button className='secondary-button life-back' onClick={() => setSection('home')}>返回人生首页</Button>
      )}

      {section === 'home' && (
        <>
          <View className='life-grid'>
            <View className='card life-entry' onClick={() => openSection('events')}>
              <View className='card-title'>人生事件</View>
              <Text className='muted'>创建、编辑、删除，并关联真实 Memory 证据。</Text>
            </View>
            <View className='card life-entry' onClick={() => openSection('stages')}>
              <View className='card-title'>人生阶段</View>
              <Text className='muted'>维护阶段与事件关系，并按证据生成长期回顾。</Text>
            </View>
            <View className='card life-entry' onClick={() => openSection('history')}>
              <View className='card-title'>多年时间线</View>
              <Text className='muted'>只读查看服务端跨年事件和阶段边界。</Text>
            </View>
            <View className='card life-entry' onClick={() => openSection('memoirs')}>
              <View className='card-title'>回忆录</View>
              <Text className='muted'>年度电子回忆录与按人生阶段生成的章节。</Text>
            </View>
          </View>
          {globalStatus && <View className='status'>{globalStatus}</View>}
        </>
      )}

      {section === 'events' && (
        <>
          <View className='card'>
            <View className='section-heading'>
              <View>
                <View className='card-title'>人生事件</View>
                <Text className='muted'>事件本身是明确记录，不使用 AI 标签。</Text>
              </View>
              <Button
                className='secondary-button compact'
                disabled={mutating}
                onClick={() => {
                  setSelectedEvent(null)
                  setEventEvidence([])
                  setEventDraft(blankEventDraft())
                  setEventFormMode('create')
                  if (placeChoices.length === 0) {
                    void listPlaces(100)
                      .then((places) => setPlaceChoices(places))
                      .catch((error) => setEventStatus(mutationError(error, '地点加载失败')))
                  }
                  setEventStatus('')
                }}
              >
                新建
              </Button>
            </View>
            {eventsLoading && <Text className='muted'>正在加载…</Text>}
            {!eventsLoading && events.length === 0 && <Text className='muted'>还没有人生事件。</Text>}
            {events.map((event) => (
              <View className='record-row' key={event.id} onClick={() => void loadEventDetail(event.id)}>
                <View>
                  <View className='record-title'>{event.title}</View>
                  <Text className='muted'>{EVENT_LABELS[event.event_kind]} · {event.started_at}</Text>
                </View>
                <Text className='arrow'>›</Text>
              </View>
            ))}
          </View>

          {eventFormMode !== 'none' && (
            <View className='card'>
              <View className='card-title'>{eventFormMode === 'create' ? '新建事件' : '编辑事件'}</View>
              <Picker
                mode='selector'
                range={LIFE_EVENT_KINDS.map((kind) => EVENT_LABELS[kind])}
                value={LIFE_EVENT_KINDS.indexOf(eventDraft.eventKind)}
                onChange={(event) => setEventDraft((current) => ({
                  ...current,
                  eventKind: LIFE_EVENT_KINDS[Number(event.detail.value)] || 'WORK',
                  customLabel: (LIFE_EVENT_KINDS[Number(event.detail.value)] || 'WORK') === 'OTHER'
                    ? current.customLabel
                    : '',
                }))}
              >
                <View className='field picker-field'>类型：{EVENT_LABELS[eventDraft.eventKind]}</View>
              </Picker>
              {eventDraft.eventKind === 'OTHER' && (
                <Input
                  className='field'
                  maxlength={120}
                  placeholder='自定义事件类型'
                  value={eventDraft.customLabel}
                  onInput={(event) => setEventDraft((current) => ({ ...current, customLabel: event.detail.value }))}
                />
              )}
              <Input
                className='field'
                maxlength={240}
                placeholder='事件标题'
                value={eventDraft.title}
                onInput={(event) => setEventDraft((current) => ({ ...current, title: event.detail.value }))}
              />
              <Input
                className='field'
                placeholder='开始时间（带时区 ISO）'
                value={eventDraft.startedAt}
                onInput={(event) => setEventDraft((current) => ({ ...current, startedAt: event.detail.value }))}
              />
              <Input
                className='field'
                placeholder='结束时间（可留空）'
                value={eventDraft.endedAt}
                onInput={(event) => setEventDraft((current) => ({ ...current, endedAt: event.detail.value }))}
              />
              <Picker
                mode='selector'
                range={['不关联地点', ...placeChoices.map((place) => place.name)]}
                value={eventDraft.placeId
                  ? Math.max(0, placeChoices.findIndex((place) => place.id === eventDraft.placeId) + 1)
                  : 0}
                onChange={(event) => {
                  const index = Number(event.detail.value)
                  setEventDraft((current) => ({
                    ...current,
                    placeId: index <= 0 ? '' : (placeChoices[index - 1]?.id || ''),
                  }))
                }}
              >
                <View className='field picker-field'>
                  地点：{eventDraft.placeId
                    ? (placeChoices.find((place) => place.id === eventDraft.placeId)?.name || '已关联地点')
                    : '不关联地点'}
                </View>
              </Picker>
              <Textarea
                className='field textarea'
                maxlength={5000}
                placeholder='备注（可留空）'
                value={eventDraft.note}
                onInput={(event) => setEventDraft((current) => ({ ...current, note: event.detail.value }))}
              />
              <View className='action-row'>
                <Button
                  className='secondary-button compact'
                  disabled={mutating}
                  onClick={() => setEventFormMode('none')}
                >
                  取消
                </Button>
                <Button className='primary-button compact' disabled={mutating} onClick={() => void saveEvent()}>
                  {mutating ? '处理中…' : '保存'}
                </Button>
              </View>
            </View>
          )}

          {selectedEvent && eventFormMode === 'none' && (
            <View className='card'>
              <View className='card-title'>{selectedEvent.title}</View>
              <View className='detail-line'>类型：{EVENT_LABELS[selectedEvent.event_kind]}</View>
              <View className='detail-line'>开始：{selectedEvent.started_at}</View>
              <View className='detail-line'>结束：{selectedEvent.ended_at || '未设置'}</View>
              <View className='detail-line'>备注：{selectedEvent.note || '未填写'}</View>
              {selectedEvent.place_id && (
                <View className='detail-line'>
                  地点：{placeChoices.find((place) => place.id === selectedEvent.place_id)?.name || shortId(selectedEvent.place_id)}
                </View>
              )}
              <View className='action-row'>
                <Button
                  className='secondary-button compact'
                  disabled={mutating}
                  onClick={() => {
                    setEventDraft(eventDraftFrom(selectedEvent))
                    setEventFormMode('edit')
                  }}
                >
                  编辑
                </Button>
                <Button className='danger-button compact' disabled={mutating} onClick={() => void confirmDeleteEvent()}>
                  删除
                </Button>
              </View>

              <View className='subheading'>Memory 证据</View>
              {eventEvidence.length === 0 && <Text className='muted'>尚未关联记忆证据。</Text>}
              {eventEvidence.map((evidence) => (
                <View className='evidence-row' key={evidence.link_id}>
                  <View>
                    <View>{evidence.title || evidence.content}</View>
                    <Text className='muted'>{evidence.source_type} · {evidence.occurred_at}</Text>
                  </View>
                  <Button
                    className='secondary-button mini-button'
                    disabled={mutating}
                    onClick={() => void unlinkMemory(evidence.memory_id)}
                  >
                    取消关联
                  </Button>
                </View>
              ))}
              {availableMemories.length > 0 && (
                <>
                  <Picker
                    mode='selector'
                    range={availableMemories.map((memory) => memory.title || memory.content.slice(0, 36))}
                    value={Math.min(memoryChoiceIndex, availableMemories.length - 1)}
                    onChange={(event) => setMemoryChoiceIndex(Number(event.detail.value))}
                  >
                    <View className='field picker-field'>
                      选择记忆：{availableMemories[Math.min(memoryChoiceIndex, availableMemories.length - 1)]?.title
                        || availableMemories[Math.min(memoryChoiceIndex, availableMemories.length - 1)]?.content.slice(0, 36)}
                    </View>
                  </Picker>
                  <Button className='secondary-button' disabled={mutating} onClick={() => void linkSelectedMemory()}>
                    关联这条记忆
                  </Button>
                </>
              )}
            </View>
          )}
          {eventStatus && <View className={eventStatus.includes('失败') ? 'error' : 'status'}>{eventStatus}</View>}
        </>
      )}

      {section === 'stages' && (
        <>
          <View className='card'>
            <View className='section-heading'>
              <View>
                <View className='card-title'>人生阶段</View>
                <Text className='muted'>阶段允许开放结束时间；不会按标题或日期自动关联事件。</Text>
              </View>
              <Button
                className='secondary-button compact'
                disabled={mutating}
                onClick={() => {
                  setSelectedStage(null)
                  setStageEvidence([])
                  setStageDraft(blankStageDraft())
                  setStageFormMode('create')
                  setStageStatus('')
                }}
              >
                新建
              </Button>
            </View>
            {stagesLoading && <Text className='muted'>正在加载…</Text>}
            {!stagesLoading && stages.length === 0 && <Text className='muted'>还没有人生阶段。</Text>}
            {stages.map((stage) => (
              <View className='record-row' key={stage.id} onClick={() => void loadStageDetail(stage.id)}>
                <View>
                  <View className='record-title'>{stage.title}</View>
                  <Text className='muted'>
                    {STAGE_LABELS[stage.stage_kind]} · {stage.started_at} → {stage.ended_at || '开放'}
                  </Text>
                </View>
                <Text className='arrow'>›</Text>
              </View>
            ))}
          </View>

          {stageFormMode !== 'none' && (
            <View className='card'>
              <View className='card-title'>{stageFormMode === 'create' ? '新建阶段' : '编辑阶段'}</View>
              <Picker
                mode='selector'
                range={LIFE_STAGE_KINDS.map((kind) => STAGE_LABELS[kind])}
                value={LIFE_STAGE_KINDS.indexOf(stageDraft.stageKind)}
                onChange={(event) => setStageDraft((current) => ({
                  ...current,
                  stageKind: LIFE_STAGE_KINDS[Number(event.detail.value)] || 'WORK',
                  customLabel: (LIFE_STAGE_KINDS[Number(event.detail.value)] || 'WORK') === 'OTHER'
                    ? current.customLabel
                    : '',
                }))}
              >
                <View className='field picker-field'>类型：{STAGE_LABELS[stageDraft.stageKind]}</View>
              </Picker>
              {stageDraft.stageKind === 'OTHER' && (
                <Input
                  className='field'
                  maxlength={120}
                  placeholder='自定义阶段类型'
                  value={stageDraft.customLabel}
                  onInput={(event) => setStageDraft((current) => ({ ...current, customLabel: event.detail.value }))}
                />
              )}
              <Input
                className='field'
                maxlength={240}
                placeholder='阶段标题'
                value={stageDraft.title}
                onInput={(event) => setStageDraft((current) => ({ ...current, title: event.detail.value }))}
              />
              <Input
                className='field'
                placeholder='开始时间（带时区 ISO）'
                value={stageDraft.startedAt}
                onInput={(event) => setStageDraft((current) => ({ ...current, startedAt: event.detail.value }))}
              />
              <Input
                className='field'
                placeholder='结束时间（可留空表示开放）'
                value={stageDraft.endedAt}
                onInput={(event) => setStageDraft((current) => ({ ...current, endedAt: event.detail.value }))}
              />
              <Textarea
                className='field textarea'
                maxlength={5000}
                placeholder='备注（可留空）'
                value={stageDraft.note}
                onInput={(event) => setStageDraft((current) => ({ ...current, note: event.detail.value }))}
              />
              <View className='action-row'>
                <Button className='secondary-button compact' disabled={mutating} onClick={() => setStageFormMode('none')}>
                  取消
                </Button>
                <Button className='primary-button compact' disabled={mutating} onClick={() => void saveStage()}>
                  {mutating ? '处理中…' : '保存'}
                </Button>
              </View>
            </View>
          )}

          {selectedStage && stageFormMode === 'none' && (
            <>
              <View className='card'>
                <View className='card-title'>{selectedStage.title}</View>
                <View className='detail-line'>类型：{STAGE_LABELS[selectedStage.stage_kind]}</View>
                <View className='detail-line'>开始：{selectedStage.started_at}</View>
                <View className='detail-line'>结束：{selectedStage.ended_at || '开放'}</View>
                <View className='detail-line'>备注：{selectedStage.note || '未填写'}</View>
                <View className='action-row'>
                  <Button
                    className='secondary-button compact'
                    disabled={mutating}
                    onClick={() => {
                      setStageDraft(stageDraftFrom(selectedStage))
                      setStageFormMode('edit')
                    }}
                  >
                    编辑
                  </Button>
                  <Button className='danger-button compact' disabled={mutating} onClick={() => void confirmDeleteStage()}>
                    删除
                  </Button>
                </View>

                <View className='subheading'>关联事件</View>
                {stageEvidence.length === 0 && <Text className='muted'>尚未关联事件。</Text>}
                {stageEvidence.map((event) => (
                  <View className='evidence-row' key={event.link_id}>
                    <View>
                      <View>{event.title}</View>
                      <Text className='muted'>{EVENT_LABELS[event.event_kind]} · {event.started_at}</Text>
                    </View>
                    <Button
                      className='secondary-button mini-button'
                      disabled={mutating}
                      onClick={() => void unlinkStageEvent(event.life_event_id)}
                    >
                      取消关联
                    </Button>
                  </View>
                ))}
                {availableEvents.length > 0 && (
                  <>
                    <Picker
                      mode='selector'
                      range={availableEvents.map((event) => event.title)}
                      value={Math.min(eventChoiceIndex, availableEvents.length - 1)}
                      onChange={(event) => setEventChoiceIndex(Number(event.detail.value))}
                    >
                      <View className='field picker-field'>
                        选择事件：{availableEvents[Math.min(eventChoiceIndex, availableEvents.length - 1)]?.title}
                      </View>
                    </Picker>
                    <Button className='secondary-button' disabled={mutating} onClick={() => void linkSelectedEvent()}>
                      关联这个事件
                    </Button>
                  </>
                )}
              </View>

              <View className='card'>
                <View className='card-title'>长期回顾</View>
                <Text className='muted'>这是 AI 生成面；只有主动点击后才调用，引用仍保持自己的来源身份。</Text>
                <Textarea
                  className='field textarea'
                  maxlength={2000}
                  placeholder='例如：这个阶段有哪些持续发生的工作变化？'
                  value={reasonQuestion}
                  onInput={(event) => {
                    reasoningAuthority.current.invalidate()
                    setReasonQuestion(event.detail.value)
                    setReasoning(null)
                  }}
                />
                <Button
                  className='primary-button'
                  disabled={reasoningLoading || mutating}
                  onClick={() => void generateReasoning()}
                >
                  {reasoningLoading ? '正在根据证据整理…' : '生成证据回顾'}
                </Button>
                {reasoning && reasonPresentation && (
                  <View className='ai-result'>
                    <View className={'trust-badge trust-' + reasonPresentation.tone}>{reasonPresentation.label}</View>
                    <Text className='muted'>{reasonPresentation.detail}</Text>
                    {reasonPresentation.state === 'INFERRED' && reasoning.answer && (
                      <View className='generated-copy'>{reasoning.answer}</View>
                    )}
                    {reasoning.citations.map((citation) => (
                      <View className='citation' key={citation.slot}>
                        <View>{citation.slot} · {citation.kind}</View>
                        <Text className='muted'>
                          Memory {shortId(citation.memory_id)} · Event {shortId(citation.life_event_id)}
                          {' · '}Stage {shortId(citation.life_stage_id)}
                          {citation.memory_trust_state ? ' · ' + citation.memory_trust_state : ''}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}
              </View>
            </>
          )}
          {stageStatus && <View className={stageStatus.includes('失败') ? 'error' : 'status'}>{stageStatus}</View>}
        </>
      )}

      {section === 'history' && (
        <View className='card'>
          <View className='card-title'>多年时间线</View>
          <Text className='muted'>这是服务端确定性投影，不是 AI 推断。游标按原值续传。</Text>
          <View className='range-row'>
            <Input
              className='field'
              type='number'
              placeholder='开始年份'
              value={historyStart}
              onInput={(event) => {
                historyAuthority.current.invalidate()
                setHistoryStart(event.detail.value)
                setHistory(null)
                setHistoryItems([])
                setHistoryCursor(null)
              }}
            />
            <Input
              className='field'
              type='number'
              placeholder='结束年份'
              value={historyEnd}
              onInput={(event) => {
                historyAuthority.current.invalidate()
                setHistoryEnd(event.detail.value)
                setHistory(null)
                setHistoryItems([])
                setHistoryCursor(null)
              }}
            />
          </View>
          <Button className='primary-button' disabled={historyLoading} onClick={() => void loadHistory(false)}>
            {historyLoading ? '加载中…' : '查看时间线'}
          </Button>
          {history && (
            <View className='history-meta muted'>
              服务端范围：{history.start_year}–{history.end_year} · {history.timezone} · as_of {history.as_of}
            </View>
          )}
          {historyItems.map((item, index) => (
            <View className='timeline-row' key={item.kind + ':' + item.occurred_at + ':' + index}>
              <View className='timeline-dot' />
              <View>
                <View className='record-title'>{item.title}</View>
                <Text className='muted'>{item.kind} · {item.occurred_at}</Text>
              </View>
            </View>
          ))}
          {historyCursor && (
            <Button className='secondary-button' disabled={historyLoading} onClick={() => void loadHistory(true)}>
              加载更多
            </Button>
          )}
          {historyStatus && <View className='error'>{historyStatus}</View>}
        </View>
      )}

      {section === 'memoirs' && (
        <>
          <View className='card'>
            <View className='card-title'>年度电子回忆录</View>
            <Text className='muted'>AI 标签只标记生成叙事；时间线和已验证照片仍是独立的确定性数据。</Text>
            <Input
              className='field'
              type='number'
              maxlength={4}
              placeholder='年度，例如 2025'
              value={annualYear}
              onInput={(event) => changeAnnualYear(event.detail.value)}
            />
            <Button className='primary-button' disabled={annualLoading} onClick={() => void runAnnualMemoir()}>
              {annualLoading ? '正在整理年度回忆…' : '生成年度回忆录'}
            </Button>
            {annual && annualPresentation && (
              <>
                <View className='memoir-meta muted'>
                  {annual.target_year} · {annual.timezone} · {annual.status}
                </View>
                <View className='subheading'>年度叙事</View>
                <View className={'trust-badge trust-' + annualPresentation.tone}>{annualPresentation.label}</View>
                <Text className='muted'>{annualPresentation.detail}</Text>
                {annualPresentation.state === 'INFERRED' && annual.narrative && (
                  <View className='generated-copy'>{annual.narrative}</View>
                )}
                {annual.narrative_citations.map((citation) => (
                  <View className='citation' key={citation.slot}>
                    <View>{citation.slot} · {citation.kind}</View>
                    <Text className='muted'>
                      Memory {shortId(citation.memory_id)} · Visit {shortId(citation.visit_id)}
                      {citation.trust_state ? ' · ' + citation.trust_state : ''}
                    </Text>
                  </View>
                ))}

                <View className='subheading'>年度时间线</View>
                {annualTimelineItems.map((item, index) => (
                  <View className='record-row' key={'annual-history:' + index + ':' + item.occurred_at}>
                    <View>
                      <View className='record-title'>{item.title}</View>
                      <Text className='muted'>{item.kind} · {item.occurred_at}</Text>
                    </View>
                  </View>
                ))}
                {annualTimelineCursor && (
                  <Button className='secondary-button' onClick={() => void loadMoreAnnualTimeline()}>
                    继续加载年度时间线
                  </Button>
                )}

                <View className='subheading'>已验证照片</View>
                {annualPhotos.length === 0 && <Text className='muted'>这个年度没有可展示的已验证照片。</Text>}
                <View className='photo-grid'>
                  {annualPhotos.map((photo) => (
                    <View className='photo-card' key={photo.media_id}>
                      <View className='record-title'>{photo.title || '照片记忆'}</View>
                      <Text className='muted'>{photo.occurred_at}</Text>
                      <Text className='muted'>{photo.content_type} · media {shortId(photo.media_id)}</Text>
                      <Button className='secondary-button mini-button' onClick={() => void previewAnnualPhoto(photo.media_id)}>
                        查看照片
                      </Button>
                    </View>
                  ))}
                </View>
                {annualPhotoCursor && (
                  <Button className='secondary-button' onClick={() => void loadMoreAnnualPhotos()}>
                    加载更多照片
                  </Button>
                )}
              </>
            )}
            {annualStatus && <View className='error'>{annualStatus}</View>}
          </View>

          <View className='card'>
            <View className='card-title'>人生回忆录</View>
            <Text className='muted'>阶段索引是确定性数据；只有你点击“生成章节”后才会调用 AI。</Text>
            <Button className='secondary-button' disabled={memoirIndexLoading} onClick={() => void loadMemoirStages(false)}>
              {memoirIndexLoading ? '正在加载阶段…' : '刷新阶段索引'}
            </Button>
            {memoirIndex.map((item) => (
              <View
                className={selectedMemoirStageId === item.life_stage_id ? 'record-row selected-row' : 'record-row'}
                key={item.life_stage_id}
                onClick={() => selectMemoirStage(item.life_stage_id)}
              >
                <View>
                  <View className='record-title'>{item.title}</View>
                  <Text className='muted'>
                    {STAGE_LABELS[item.stage_kind]} · {item.started_at} → {item.ended_at || '开放'}
                  </Text>
                </View>
              </View>
            ))}
            {memoirCursor && (
              <Button className='secondary-button' disabled={memoirIndexLoading} onClick={() => void loadMemoirStages(true)}>
                加载更多阶段
              </Button>
            )}
            {selectedMemoirStageId && (
              <Button className='primary-button' disabled={chapterLoading} onClick={() => void generateChapter()}>
                {chapterLoading ? '正在生成章节…' : '按这个阶段生成章节'}
              </Button>
            )}
            {chapter && chapterPresentation && (
              <View className='ai-result'>
                <View className={'trust-badge trust-' + chapterPresentation.tone}>{chapterPresentation.label}</View>
                <Text className='muted'>{chapterPresentation.detail}</Text>
                {chapterPresentation.state === 'INFERRED' && chapter.narrative && (
                  <View className='generated-copy'>{chapter.narrative}</View>
                )}
                {chapter.citations.map((citation) => (
                  <View className='citation' key={citation.slot}>
                    <View>{citation.slot} · {citation.kind}</View>
                    <Text className='muted'>
                      Stage {shortId(citation.life_stage_id)} · Event {shortId(citation.life_event_id)}
                      {' · '}Memory {shortId(citation.memory_id)}
                      {citation.memory_trust_state ? ' · ' + citation.memory_trust_state : ''}
                    </Text>
                  </View>
                ))}
              </View>
            )}
            {memoirStatus && <View className='error'>{memoirStatus}</View>}
          </View>
        </>
      )}
    </View>
  )
}
