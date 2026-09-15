import { Text, View } from '@tarojs/components'
import './index.scss'

export default function Page() {
  return (
    <View className='page'>
      <View className='title'>家庭</View>
      <View className='subtitle'>共享必须逐项授权。</View>
      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>实时位置、足迹、个人记忆和照片默认都不向家庭成员开放。</Text>
      </View>
    </View>
  )
}
