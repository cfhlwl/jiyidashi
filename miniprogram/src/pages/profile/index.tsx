import { Text, View } from '@tarojs/components'
import './index.scss'

export default function Page() {
  return (
    <View className='page'>
      <View className='title'>我的</View>
      <View className='subtitle'>你的记忆由你控制。</View>
      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>提供暂停记录、隐私权限、数据导出、删除与长辈模式。</Text>
      </View>
    </View>
  )
}
