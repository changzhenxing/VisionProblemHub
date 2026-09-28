<script setup>
import StatusPill from './StatusPill.vue'

defineProps({ events: { type: Array, default: () => [] } })
</script>

<template>
  <div class="timeline">
    <div v-for="event in [...events].reverse()" :key="event.id" class="event">
      <div class="event-head"><StatusPill :value="event.event_type" /> <StatusPill v-if="event.outcome" :value="event.outcome" /> · {{ event.actor_name }} · {{ event.created_at }}</div>
      <div class="event-content">{{ event.content }}</div>
      <details v-if="event.metadata"><summary class="muted">变更详情</summary><pre>{{ JSON.stringify(event.metadata, null, 2) }}</pre></details>
      <div class="attachments">
        <div v-for="file in event.attachments" :key="file.id" class="attachment">
          <img v-if="file.media_kind === 'image'" :src="file.url" :alt="file.name" loading="lazy" />
          <video v-else-if="file.media_kind === 'video'" :src="file.url" controls preload="metadata" />
          <a v-else :href="file.url" target="_blank" rel="noopener noreferrer">📎 {{ file.name }}</a>
          <small>{{ file.role }} · {{ file.name }}</small>
        </div>
      </div>
    </div>
  </div>
</template>
