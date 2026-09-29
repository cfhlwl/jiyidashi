import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import './product.scss'

type ProductHeroHeaderProps = {
  eyebrow?: string
  title: string
  subtitle?: string
}

export function ProductHeroHeader({ eyebrow, title, subtitle }: ProductHeroHeaderProps) {
  return (
    <View className='product-hero'>
      {eyebrow && <Text className='product-hero-eyebrow'>{eyebrow}</Text>}
      <View className='product-hero-title'>{title}</View>
      {subtitle && <View className='product-hero-subtitle'>{subtitle}</View>}
    </View>
  )
}

type ProductSectionHeaderProps = {
  title: string
  subtitle?: string
  actionText?: string
  onAction?: () => void
}

export function ProductSectionHeader({ title, subtitle, actionText, onAction }: ProductSectionHeaderProps) {
  return (
    <View className='product-section-header'>
      <View className='product-section-copy'>
        <View className='product-section-title'>{title}</View>
        {subtitle && <Text className='product-section-subtitle'>{subtitle}</Text>}
      </View>
      {actionText && onAction && (
        <Button className='product-section-action' onClick={onAction}>{actionText}</Button>
      )}
    </View>
  )
}

type AiDisclosureProps = {
  label?: string
  detail: string
}

export function AiDisclosure({ label = 'AI 帮你整理', detail }: AiDisclosureProps) {
  return (
    <View className='product-ai-disclosure'>
      <Text className='product-ai-mark'>AI</Text>
      <View>
        <View className='product-ai-title'>{label}</View>
        <Text className='product-ai-detail'>{detail}</Text>
      </View>
    </View>
  )
}

type ProductStatePanelProps = {
  kind?: 'info' | 'success' | 'warning' | 'error'
  title: string
  message: string
  actionText?: string
  onAction?: () => void
}

export function ProductStatePanel({
  kind = 'info',
  title,
  message,
  actionText,
  onAction,
}: ProductStatePanelProps) {
  return (
    <View className={`product-state product-state-${kind}`}>
      <View className='product-state-title'>{title}</View>
      <Text className='product-state-message'>{message}</Text>
      {actionText && onAction && (
        <Button className='secondary-button product-state-action' onClick={onAction}>{actionText}</Button>
      )}
    </View>
  )
}

type FloatingCaptureActionProps = {
  elderMode?: boolean
}

export function FloatingCaptureAction({ elderMode = false }: FloatingCaptureActionProps) {
  const openCapture = () => {
    void Taro.navigateTo({ url: '/pages/capture/index' })
  }

  return (
    <View className={elderMode ? 'floating-capture-shell floating-capture-elder' : 'floating-capture-shell'}>
      <Button className='floating-capture-action' onClick={openCapture}>
        <Text className='floating-capture-plus'>＋</Text>
        <Text>记一下</Text>
      </Button>
    </View>
  )
}
