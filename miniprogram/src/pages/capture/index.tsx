import { Text, View } from '@tarojs/components'
import './index.scss'

export default function Page() {
  return (
    <View className='page'>
      <View className='title'>记一下</View>
      <View className='subtitle'>把重要的事情说出来。</View>
      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>支持文字、语音、拍照记录。V1 首先保证记录可以被可靠找回。</Text>
      </View>
    </View>
  )
}
