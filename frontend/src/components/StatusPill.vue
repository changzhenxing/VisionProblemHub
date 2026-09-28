<script setup>
import { computed } from 'vue'

const props = defineProps({ value: { type: [String, Number], default: '' } })
const tone = computed(() => {
  if (['阻塞', '紧急重要'].includes(props.value) || String(props.value).startsWith('延期')) return 'red'
  if (['有风险', '重要不紧急'].includes(props.value)) return 'yellow'
  if (['正常', '已关闭', '成功', '人工确认', '多项目验证'].includes(props.value)) return 'green'
  if (['处理中', '待处理'].includes(props.value)) return 'blue'
  return ''
})
</script>

<template><span class="pill" :class="tone">{{ value }}</span></template>
