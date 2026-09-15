import { Text, View } from '@tarojs/components'
import './index.scss'

export default function Page() {
  return (
    <View className='page'>
      <View className='title'>问记忆</View>
      <View className='subtitle'>从自己的记忆证据里找答案。</View>
      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>没有证据时必须返回“没有找到”，不能让 AI 猜测个人事实。</Text>
      </View>
    </View>
  )
}
