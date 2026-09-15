import { Text, View } from '@tarojs/components'
import './index.scss'

export default function Page() {
  return (
    <View className='page'>
      <View className='title'>今天</View>
      <View className='subtitle'>你负责生活，我帮你记住。</View>
      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>APP 端负责主要自动足迹；小程序提供快速查看和记录入口。</Text>
      </View>
    </View>
  )
}
