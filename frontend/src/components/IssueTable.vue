<script setup>
import StatusPill from './StatusPill.vue'

defineProps({ issues: { type: Array, default: () => [] } })
const emit = defineEmits(['open'])
const date = (value) => value ? String(value).slice(0, 10) : ''
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>项目</th><th>类型</th><th>问题</th><th>优先级</th><th>状态</th><th>Owner</th><th>计划关闭</th><th>延期</th></tr></thead>
      <tbody>
        <tr v-for="issue in issues" :key="issue.id" class="clickable" @click="emit('open', issue.id)">
          <td>{{ issue.project_name }}</td><td><StatusPill :value="issue.issue_type" /></td>
          <td class="issue-title">{{ issue.description }}</td><td><StatusPill :value="issue.priority" /></td>
          <td><StatusPill :value="issue.status" /></td><td>{{ issue.owner_name }}</td>
          <td>{{ date(issue.planned_close_date) }}</td>
          <td><StatusPill v-if="issue.is_delayed" :value="`延期${issue.delay_days}天`" /><span v-else>-</span></td>
        </tr>
        <tr v-if="!issues.length"><td colspan="8" class="empty">暂无问题</td></tr>
      </tbody>
    </table>
  </div>
</template>
