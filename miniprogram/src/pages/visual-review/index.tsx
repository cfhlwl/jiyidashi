import Taro from '@tarojs/taro'
import { Button, Input, Text, View } from '@tarojs/components'
import {
  AiDisclosure,
  FloatingCaptureAction,
  ProductHeroHeader,
  ProductSectionHeader,
  ProductStatePanel,
} from '../../components/product/ProductUi'
import './index.scss'

type Scene =
  | 'today'
  | 'timeline'
  | 'capture'
  | 'memory'
  | 'people'
  | 'life'
  | 'family'
  | 'profile'
  | 'summary'
  | 'states'
  | 'elder'

function ReviewRow({ title, subtitle, meta }: { title: string; subtitle?: string; meta?: string }) {
  return (
    <View className='review-row'>
      <View className='review-row-copy'>
        <View className='review-row-title'>{title}</View>
        {subtitle && <Text className='review-row-subtitle'>{subtitle}</Text>}
      </View>
      {meta && <Text className='review-row-meta'>{meta}</Text>}
    </View>
  )
}

function TodayScene() {
  return (
    <>
      <ProductHeroHeader
        eyebrow='迹忆 · 今天'
        title='今天'
        subtitle='把今天真实形成的足迹、地点和回忆放在一起，安静地回看一天。'
      />
      <ProductSectionHeader title='今天的足迹' subtitle='只展示已经形成的记录' />
      <View className='card review-card'>
        <ReviewRow title='上海办公室' subtitle='08:10 – 10:20' meta='已稳定' />
        <ReviewRow title='周末咖啡店' subtitle='14:30 – 15:40' meta='已稳定' />
      </View>
      <ProductSectionHeader title='今天记下的' />
      <View className='card review-card'>
        <ReviewRow title='第一次产品讨论' subtitle='那天把第一版方向写满了整块白板。' meta='09:15' />
      </View>
      <FloatingCaptureAction />
    </>
  )
}

function TimelineScene() {
  return (
    <>
      <ProductHeroHeader
        eyebrow='迹忆 · 记忆'
        title='时间线'
        subtitle='把地点和已经形成的记录按时间串在一起。'
      />
      <View className='review-timeline'>
        <View className='review-timeline-item'>
          <View className='review-dot' />
          <View className='card review-timeline-card'>
            <Text className='review-time'>09:15</Text>
            <View className='card-title'>第一次产品讨论</View>
            <Text className='muted'>上海办公室 · 产品方向</Text>
          </View>
        </View>
        <View className='review-timeline-item'>
          <View className='review-dot' />
          <View className='card review-timeline-card'>
            <Text className='review-time'>14:30</Text>
            <View className='card-title'>周末咖啡店</View>
            <Text className='muted'>一段安静的下午记录</Text>
          </View>
        </View>
      </View>
    </>
  )
}

function CaptureScene() {
  return (
    <>
      <ProductHeroHeader eyebrow='迹忆 · 记录' title='记一下' subtitle='写下、拍下或录下现在想记住的事。' />
      <View className='card'>
        <View className='card-title'>写下来</View>
        <Input className='field' value='第一次产品讨论' disabled />
        <View className='review-textarea'>那天我们把第一版产品方向写满了整块白板。</View>
        <Button className='primary-button'>保存这条记忆</Button>
      </View>
      <View className='review-action-grid'>
        <View className='card review-action-card'>
          <Text className='review-action-icon'>▣</Text>
          <View className='card-title'>拍一张</View>
          <Text className='muted'>照片确认后再保存</Text>
        </View>
        <View className='card review-action-card'>
          <Text className='review-action-icon'>◉</Text>
          <View className='card-title'>录一段</View>
          <Text className='muted'>帮你整理成文字</Text>
        </View>
      </View>
    </>
  )
}

function MemoryScene() {
  return (
    <>
      <ProductHeroHeader
        eyebrow='迹忆 · 记忆'
        title='记忆'
        subtitle='从自己的记录里查找过去发生的事；没有足够记录时不会猜。'
      />
      <View className='card'>
        <View className='card-title'>问一个问题</View>
        <Input className='field' value='护照放在哪里？' disabled />
        <Button className='primary-button'>从我的记录里找</Button>
      </View>
      <View className='card'>
        <Text className='review-trust'>明确记录</Text>
        <View className='card-title'>护照最后记录在书房抽屉。</View>
        <Text className='muted'>参考记录 1 · 2026-09-20</Text>
      </View>
    </>
  )
}

function PeopleScene() {
  return (
    <>
      <ProductHeroHeader
        eyebrow='迹忆 · 重要的人'
        title='重要的人'
        subtitle='记录生命中重要的人。只有你主动添加的人才会出现在这里。'
      />
      <View className='card review-card'>
        <ReviewRow title='老张' subtitle='朋友 · 认识至少 577 天' meta='3 条记忆' />
        <ReviewRow title='小李' subtitle='同事' meta='2 条记忆' />
      </View>
      <Button className='secondary-button'>添加重要的人</Button>
    </>
  )
}

function LifeScene() {
  return (
    <>
      <ProductHeroHeader eyebrow='迹忆 · 人生' title='我的人生' subtitle='把重要经历、人生阶段和跨年的故事慢慢整理在一起。' />
      <View className='review-action-list'>
        <ReviewRow title='人生阶段' subtitle='产品创业阶段 · 2025 – 至今' meta='›' />
        <ReviewRow title='人生经历' subtitle='第一次正式发布' meta='›' />
        <ReviewRow title='年度回顾' subtitle='回看一整年的重要记录' meta='›' />
        <ReviewRow title='人生故事' subtitle='按人生阶段整理故事' meta='›' />
      </View>
    </>
  )
}

function FamilyScene() {
  return (
    <>
      <ProductHeroHeader
        eyebrow='迹忆 · 家庭'
        title='家庭'
        subtitle='每一项共享都由你明确授权，位置权限需要单独开启。'
      />
      <View className='card'>
        <View className='card-title'>家庭成员 1</View>
        <Text className='muted'>家庭成员</Text>
        <View className='review-permission'>
          <Text>可查看我的记忆</Text>
          <Text className='review-switch review-switch-on'>开启</Text>
        </View>
        <View className='review-permission'>
          <Text>可查看我的照片</Text>
          <Text className='review-switch review-switch-on'>开启</Text>
        </View>
        <View className='review-permission'>
          <View>
            <View>可查看我的当前位置</View>
            <Text className='muted'>位置需要单独授权</Text>
          </View>
          <Text className='review-switch'>关闭</Text>
        </View>
      </View>
    </>
  )
}

function ProfileScene() {
  return (
    <>
      <ProductHeroHeader eyebrow='迹忆 · 我的' title='我的' subtitle='管理账号、隐私和记录方式。你的记忆由你控制。' />
      <View className='card review-card'>
        <ReviewRow title='测试用户' subtitle='golden@example.com' />
        <ReviewRow title='时区' subtitle='Asia/Shanghai' />
      </View>
      <View className='card'>
        <View className='card-title'>隐私与记录控制</View>
        <Text className='muted'>你可以随时暂停自动记录，不会删除已经保存的内容。</Text>
        <Button className='secondary-button'>暂停记录</Button>
      </View>
    </>
  )
}

function SummaryScene() {
  return (
    <>
      <ProductHeroHeader eyebrow='迹忆 · 回忆总结' title='这一年' subtitle='用已经记录的地点、照片和重要经历回看 2025。' />
      <View className='review-stat-grid'>
        <View className='card review-stat'><View className='review-stat-number'>18</View><Text className='muted'>重要记录</Text></View>
        <View className='card review-stat'><View className='review-stat-number'>6</View><Text className='muted'>常去地点</Text></View>
      </View>
      <AiDisclosure detail='基于你的记录整理，你可以查看参考记录。' />
      <View className='card'>
        <View className='card-title'>年度回顾</View>
        <Text className='muted'>这一年开始了新的产品阶段，也留下了许多值得回看的片段。</Text>
      </View>
    </>
  )
}

function StatesScene() {
  return (
    <>
      <ProductHeroHeader eyebrow='迹忆 · 状态' title='保持清楚' subtitle='每一种状态都告诉你发生了什么，以及下一步可以做什么。' />
      <ProductStatePanel kind='error' title='当前离线' message='暂时无法连接网络。联网后可以重试。' />
      <View className='review-gap' />
      <ProductStatePanel kind='warning' title='暂时无法整理' message='这次没有整理成功，可以稍后再试。' />
      <View className='review-gap' />
      <View className='card review-empty'>
        <Text className='review-empty-icon'>○</Text>
        <View className='card-title'>还没有记录</View>
        <Text className='muted'>记下一件事后，它会出现在这里。</Text>
      </View>
    </>
  )
}

function ElderScene() {
  return (
    <View className='elder-mode'>
      <ProductHeroHeader
        eyebrow='迹忆 · 记忆'
        title='我想找东西'
        subtitle='只从你自己的可信记录里找；没有可靠记录时，我不会猜。'
      />
      <View className='card'>
        <View className='card-title'>你要找什么？</View>
        <Input className='field' value='我的护照在哪里？' disabled />
        <Button className='primary-button'>帮我找</Button>
      </View>
      <View className='card'>
        <View className='card-title'>没有找到足够记录</View>
        <Text className='muted'>我还不知道它在哪里。你可以换个问法，或先记下一条线索。</Text>
      </View>
    </View>
  )
}

function renderScene(scene: Scene) {
  switch (scene) {
    case 'today': return <TodayScene />
    case 'timeline': return <TimelineScene />
    case 'capture': return <CaptureScene />
    case 'memory': return <MemoryScene />
    case 'people': return <PeopleScene />
    case 'life': return <LifeScene />
    case 'family': return <FamilyScene />
    case 'profile': return <ProfileScene />
    case 'summary': return <SummaryScene />
    case 'states': return <StatesScene />
    case 'elder': return <ElderScene />
  }
}

export default function VisualReviewPage() {
  const raw = Taro.getCurrentInstance().router?.params?.scene || 'today'
  const scenes: Scene[] = [
    'today', 'timeline', 'capture', 'memory', 'people', 'life',
    'family', 'profile', 'summary', 'states', 'elder',
  ]
  const scene = (scenes.includes(raw as Scene) ? raw : 'today') as Scene
  return <View className='page visual-review'>{renderScene(scene)}</View>
}
