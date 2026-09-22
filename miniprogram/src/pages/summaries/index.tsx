import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useRef, useState } from 'react'
import {
  generateAnnualTrustedSummary,
  generateDailyTrustedSummary,
  generateMonthlyTrustedSummary,
  isAuthenticated,
} from '../../services/api'
import {
  isReadySummary,
  trustedSummaryCitationLabel,
  trustedSummaryPeriodIdentity,
  trustedSummaryStatusMessage,
  trustedSummaryTrustLabel,
  TrustedSummaryGenerationGate,
  type TrustedSummaryPeriod,
  type TrustedSummaryResult,
} from '../../services/memorySummaries'
import './index.scss'

const PERIOD_COPY: Record<TrustedSummaryPeriod, {
  tab: string
  title: string
  button: string
}> = {
  daily: {
    tab: '今天',
    title: '今日回忆',
    button: '生成今日回忆',
  },
  monthly: {
    tab: '本月',
    title: '本月回忆',
    button: '生成本月回忆',
  },
  annual: {
    tab: '年度',
    title: '年度回忆',
    button: '生成年度回忆',
  },
}

export default function Page() {
  const [period, setPeriod] = useState<TrustedSummaryPeriod>('daily')
  const [result, setResult] = useState<TrustedSummaryResult | null>(null)
  const [status, setStatus] = useState('')
  const [generating, setGenerating] = useState(false)
  const generationGate = useRef(new TrustedSummaryGenerationGate())

  const selectPeriod = (next: TrustedSummaryPeriod) => {
    if (generationGate.current.isPending() || next === period) return
    setPeriod(next)
    setResult(null)
    setStatus('')
  }

  const generate = async () => {
    if (!isAuthenticated()) {
      setResult(null)
      setStatus('请先到“我的”页面登录正式账号')
      return
    }
    if (!generationGate.current.begin()) return

    setGenerating(true)
    setResult(null)
    setStatus('')
    try {
      // [人工注释][#103] Generation is intentionally explicit-only. No lifecycle,
      // mount effect, polling, or background refresh calls any trusted summary endpoint.
      const generated = period === 'daily'
        ? await generateDailyTrustedSummary()
        : period === 'monthly'
          ? await generateMonthlyTrustedSummary()
          : await generateAnnualTrustedSummary()
      setResult(generated)
    } catch {
      // Provider/backend detail strings are intentionally not surfaced in product UI.
      setResult(null)
      setStatus('回忆总结生成失败，请稍后重试')
    } finally {
      generationGate.current.end()
      setGenerating(false)
    }
  }

  const copy = PERIOD_COPY[period]
  const ready = result ? isReadySummary(result) : false
  const typedStatus = result ? trustedSummaryStatusMessage(result.status) : ''

  return (
    <View className='page summaries-page'>
      <View className='summaries-header'>
        <Button className='back-button' onClick={() => Taro.navigateBack()}>‹ 返回</Button>
        <View>
          <View className='title'>回忆总结</View>
          <View className='subtitle'>只基于你自己的可信记忆与已完成足迹生成。</View>
        </View>
      </View>

      <View className='period-tabs' aria-label='回忆总结时间范围'>
        {(['daily', 'monthly', 'annual'] as const).map((item) => (
          <Button
            className={item === period ? 'period-tab active' : 'period-tab'}
            disabled={generating}
            key={item}
            onClick={() => selectPeriod(item)}
          >
            {PERIOD_COPY[item].tab}
          </Button>
        ))}
      </View>

      <View className='card generation-card'>
        <View className='card-title'>{copy.title}</View>
        <Text className='muted'>
          时间边界由账号时区和服务端日历规则决定。打开页面不会自动调用 AI。
        </Text>
        <Button
          className='primary-button generate-button'
          disabled={generating}
          onClick={generate}
        >
          {generating ? '正在生成…' : copy.button}
        </Button>
      </View>

      {status && (
        <View className='card'>
          <View className='error'>{status}</View>
        </View>
      )}

      {result && (
        <View className='card summary-result-card'>
          <View className='result-heading'>
            <View className='card-title'>AI 回忆总结</View>
            <View className='result-badge'>{ready ? '已生成' : '暂未生成'}</View>
          </View>

          <View className='result-meta'>
            <Text>{trustedSummaryPeriodIdentity(result)}</Text>
            <Text> · {result.timezone}</Text>
          </View>

          <View className='ai-note'>
            AI 只根据服务端冻结的可信记录生成；没有足够证据时不会编造总结。
          </View>

          {ready && result.summary && (
            <View className='summary-text'>{result.summary}</View>
          )}

          {!ready && typedStatus && (
            <View className='summary-state'>{typedStatus}</View>
          )}

          {ready && (
            <View className='citations-section'>
              <View className='section-title'>证据来源</View>
              {result.citations.map((citation) => (
                <View className='citation-row' key={citation.slot}>
                  <View>
                    <View className='citation-kind'>
                      {trustedSummaryCitationLabel(citation)}
                    </View>
                    <View className='muted'>证据槽位 {citation.slot}</View>
                  </View>
                  {citation.trust_state && (
                    <View className='trust-label'>
                      {trustedSummaryTrustLabel(citation.trust_state)}
                    </View>
                  )}
                </View>
              ))}
            </View>
          )}
        </View>
      )}

      <View className='privacy-note'>
        回忆总结不会后台自动生成，也不会用于家庭成员之间的共享。
      </View>
    </View>
  )
}
