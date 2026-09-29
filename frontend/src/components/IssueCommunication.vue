<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ issueId: Number, api: Function, users: Array, permissions: Array })
const emit = defineEmits(['openIssue'])
const feedback = ref([]), decisions = ref([]), similar = ref([]), collaborators = ref([])
const kind = ref('建议'), content = ref(''), visibility = ref('project'), recipientId = ref(''), eventId = ref(''), files = ref([])
const decision = ref({ fact: '', judgment: '', decision: '', commitment: '', owner_id: '', due_date: '', visibility: 'project' })
const newCollaborator = ref(''), error = ref('')
const can = (key) => props.permissions?.includes(key)
async function load() {
  try {
    ;[feedback.value, decisions.value, similar.value, collaborators.value] = await Promise.all([
      props.api(`/api/issues/${props.issueId}/feedback`), props.api(`/api/issues/${props.issueId}/decisions`),
      props.api(`/api/issues/${props.issueId}/similar`), props.api(`/api/issues/${props.issueId}/collaborators`),
    ])
    error.value = ''
  } catch (cause) { error.value = cause.message }
}
watch(() => props.issueId, load, { immediate: true })
async function submitFeedback() {
  try {
    const data = new FormData()
    data.append('kind', kind.value); data.append('content', content.value); data.append('visibility', visibility.value)
    if (recipientId.value) data.append('recipient_id', recipientId.value)
    if (eventId.value) data.append('event_id', eventId.value)
    files.value.forEach((file) => data.append('files', file))
    await props.api(`/api/issues/${props.issueId}/feedback`, { method: 'POST', body: data })
    content.value = ''; files.value = []; await load()
  } catch (cause) { error.value = cause.message }
}
async function submitDecision() {
  try {
    const payload = { ...decision.value, owner_id: decision.value.owner_id ? Number(decision.value.owner_id) : null }
    await props.api(`/api/issues/${props.issueId}/decisions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    decision.value = { fact: '', judgment: '', decision: '', commitment: '', owner_id: '', due_date: '', visibility: 'project' }
    await load()
  } catch (cause) { error.value = cause.message }
}
async function saveCollaborators() {
  try {
    const ids = [...new Set([...collaborators.value.map((item) => item.user_id), Number(newCollaborator.value)])]
    await props.api(`/api/issues/${props.issueId}/collaborators`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ids) })
    newCollaborator.value = ''; await load()
  } catch (cause) { error.value = cause.message }
}
async function removeCollaborator(id) {
  try {
    await props.api(`/api/issues/${props.issueId}/collaborators`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collaborators.value.filter((item) => item.user_id !== id).map((item) => item.user_id)) })
    await load()
  } catch (cause) { error.value = cause.message }
}
</script>

<template>
  <div class="communication">
    <p v-if="error" class="error">{{ error }}</p>
    <div class="grid2">
      <section class="panel"><h3>管理反馈</h3><p class="muted">围绕真实问题给出认可、建议、追问或协助。</p>
        <div v-for="item in feedback" :key="item.id" class="comm-item"><b>{{ item.kind }} · {{ item.author_name }} → {{ item.recipient_name }}</b><small> · {{ item.created_at }} · {{ item.visibility }}</small><p>{{ item.content }}</p><a v-for="file in item.attachments" :key="file.id" :href="file.url" target="_blank" rel="noopener">{{ file.name }}　</a></div>
        <p v-if="!feedback.length" class="muted">暂无反馈</p>
        <form v-if="can('feedback.write')" class="form" @submit.prevent="submitFeedback">
          <div class="form-row"><label>类型<select v-model="kind"><option v-for="item in ['认可','建议','追问','协助']" :key="item">{{ item }}</option></select></label><label>接收人<select v-model="recipientId"><option value="">问题负责人</option><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select></label></div>
          <label>反馈内容<textarea v-model="content" required maxlength="5000" /></label>
          <div class="form-row"><label>可见范围<select v-model="visibility"><option value="project">项目内</option><option value="participants">参与者</option><option value="self_manager">本人和主管</option><option value="management">管理私有</option></select></label><label>关联进展 ID（可选）<input v-model="eventId" type="number" min="1" /></label></div>
          <label>附件<input type="file" multiple @change="files = Array.from($event.target.files || [])" /></label><button class="primary">发表反馈</button>
        </form>
      </section>
      <section class="panel"><h3>沟通结论</h3><p class="muted">只沉淀事实、判断、决定和承诺。</p>
        <div v-for="item in decisions" :key="item.id" class="comm-item"><b>{{ item.author_name }} · {{ item.created_at }}</b><p v-if="item.fact">事实：{{ item.fact }}</p><p v-if="item.judgment">判断：{{ item.judgment }}</p><p v-if="item.decision">决定：{{ item.decision }}</p><p v-if="item.commitment">承诺：{{ item.commitment }} <span v-if="item.due_date">({{ item.due_date }})</span></p><small>{{ item.visibility }}</small></div>
        <p v-if="!decisions.length" class="muted">暂无结论</p>
        <form v-if="can('feedback.write')" class="form" @submit.prevent="submitDecision"><label>事实<textarea v-model="decision.fact" /></label><label>判断<textarea v-model="decision.judgment" /></label><label>决定<textarea v-model="decision.decision" /></label><label>承诺<textarea v-model="decision.commitment" /></label><div class="form-row"><label>责任人<select v-model="decision.owner_id"><option value="">问题负责人</option><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select></label><label>期限<input v-model="decision.due_date" type="date" /></label></div><label>可见范围<select v-model="decision.visibility"><option value="project">项目内</option><option value="participants">参与者</option><option value="self_manager">本人和主管</option><option value="management">管理私有</option></select></label><button class="primary">记录结论</button></form>
      </section>
    </div>
    <section class="panel"><h3>协同人员</h3><span v-for="person in collaborators" :key="person.user_id" class="comm-chip">{{ person.name }} <button v-if="can('issues.write')" @click="removeCollaborator(person.user_id)">×</button></span><div v-if="can('issues.write')" class="toolbar"><select v-model="newCollaborator"><option value="">添加协同人</option><option v-for="user in users.filter((user) => !collaborators.some((item) => item.user_id === user.id))" :key="user.id" :value="user.id">{{ user.name }}</option></select><button class="secondary" :disabled="!newCollaborator" @click="saveCollaborators">添加</button></div></section>
    <section class="panel"><h3>相似问题（规则匹配）</h3><div v-for="item in similar" :key="item.id" class="comm-item"><button class="link-button" @click="emit('openIssue', item.id)">#{{ item.id }} {{ item.description }}</button><small> · {{ item.rule }} · {{ item.status }}</small></div><p v-if="!similar.length" class="muted">暂无同类型问题</p></section>
  </div>
</template>

<style scoped>
.communication{display:grid;gap:16px}.panel{padding:16px}.comm-item{padding:12px 0;border-bottom:1px solid var(--line)}.comm-item p{white-space:pre-wrap;margin:5px 0}.comm-chip{display:inline-flex;gap:5px;margin:4px;padding:5px 9px;background:#eef2ff;border-radius:15px}.comm-chip button,.link-button{border:0;background:none;cursor:pointer;color:var(--blue)}.error{color:#ad3131}
</style>
