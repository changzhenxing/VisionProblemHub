<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({ api: { type: Function, required: true }, permissions: { type: Array, default: () => [] } })
const emit = defineEmits(['openSource'])
const canManage = computed(() => props.permissions.includes('models.manage'))
const status = ref({ configured: false, model: null })
const conversations = ref([])
const models = ref([])
const conversationId = ref(null)
const messages = ref([])
const prompt = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const showSettings = ref(false)
const selectedModelId = ref(null)
const form = ref({ name: '', base_url: '', model_name: '', api_key: '', clear_api_key: false, is_active: true })

async function refresh() {
  try {
    status.value = await props.api('/api/agent/status')
    conversations.value = await props.api('/api/agent/conversations')
    if (canManage.value) models.value = await props.api('/api/agent/models')
    error.value = ''
  } catch (cause) { error.value = cause.message }
}
onMounted(refresh)

function newConversation() { conversationId.value = null; messages.value = []; prompt.value = ''; error.value = '' }
async function openConversation(id) {
  try {
    const result = await props.api(`/api/agent/conversations/${id}`)
    conversationId.value = result.id
    messages.value = result.messages
    error.value = ''
  } catch (cause) { error.value = cause.message }
}
async function removeConversation(id) {
  if (!window.confirm('删除这段 Agent 会话及草稿？')) return
  try {
    await props.api(`/api/agent/conversations/${id}`, { method: 'DELETE' })
    if (conversationId.value === id) newConversation()
    await refresh()
  } catch (cause) { error.value = cause.message }
}
async function send() {
  const text = prompt.value.trim()
  if (!text || busy.value || !status.value.configured) return
  busy.value = true; error.value = ''; prompt.value = ''
  try {
    const result = await props.api('/api/agent/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId.value, message: text }),
    })
    conversationId.value = result.conversation_id
    messages.value.push({ role: 'user', content: text, sources: [], trace: [], actions: [] }, result.message)
    await refresh()
  } catch (cause) { prompt.value = text; error.value = cause.message }
  finally { busy.value = false }
}
async function apply(action) {
  if (!window.confirm(`确认将这条“${action.draft.event_type}”写入问题 #${action.draft.issue_id}？`)) return
  try {
    await props.api(`/api/agent/actions/${action.id}/apply`, { method: 'POST' })
    await openConversation(conversationId.value)
    notice.value = `已写入问题 #${action.draft.issue_id}`
  } catch (cause) { error.value = cause.message }
}
function editModel(model = null) {
  selectedModelId.value = model?.id || null
  form.value = model
    ? { name: model.name, base_url: model.base_url, model_name: model.model_name, api_key: '', clear_api_key: false, is_active: model.is_active }
    : { name: '', base_url: '', model_name: '', api_key: '', clear_api_key: false, is_active: true }
  showSettings.value = true; error.value = ''; notice.value = ''
}
async function saveModel() {
  busy.value = true; error.value = ''
  try {
    const path = selectedModelId.value ? `/api/agent/models/${selectedModelId.value}` : '/api/agent/models'
    await props.api(path, { method: selectedModelId.value ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form.value) })
    form.value.api_key = ''
    await refresh()
    notice.value = '模型配置已保存'
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
async function testModel(model) {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const result = await props.api(`/api/agent/models/${model.id}/test`, { method: 'POST' })
    notice.value = `连接测试成功：${result.response}`
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
async function activateModel(model) {
  busy.value = true; error.value = ''
  try {
    await props.api(`/api/agent/models/${model.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...model, is_active: true }) })
    await refresh(); notice.value = `已启用 ${model.name}`
  } catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
async function deleteModel(model) {
  if (!window.confirm(`删除模型配置“${model.name}”？已有会话的模型无法删除。`)) return
  try {
    await props.api(`/api/agent/models/${model.id}`, { method: 'DELETE' })
    await refresh(); editModel()
  } catch (cause) { error.value = cause.message }
}
</script>

<template>
  <div class="agent-page">
    <div class="page-head"><div><h1>工业视觉 Agent</h1><p>围绕项目、问题与知识提问，依据当前账号权限检索事实。</p></div>
      <button v-if="canManage" class="secondary" @click="showSettings = !showSettings">模型配置</button></div>
    <p v-if="error" class="agent-alert">{{ error }}</p>
    <p v-if="notice" class="agent-notice">{{ notice }}</p>
    <section v-if="showSettings && canManage" class="panel agent-settings">
      <div class="panel-head"><h2>第三方模型</h2><span class="muted">兼容 Chat Completions 的工具调用接口</span></div>
      <div class="agent-models"><div v-for="model in models" :key="model.id" class="agent-model">
        <div><b>{{ model.name }}</b> <span v-if="model.is_active" class="pill blue">当前使用</span><p class="muted">{{ model.model_name }} · {{ model.base_url }} · {{ model.has_api_key ? '已保存密钥' : '无密钥' }}</p></div>
        <div class="toolbar"><button class="secondary" @click="editModel(model)">编辑</button><button class="secondary" :disabled="busy" @click="testModel(model)">测试</button><button v-if="!model.is_active" class="secondary" :disabled="busy" @click="activateModel(model)">启用</button><button class="secondary danger" @click="deleteModel(model)">删除</button></div>
      </div></div>
      <button class="secondary" @click="editModel()">＋ 新增模型</button>
      <form class="form agent-config" @submit.prevent="saveModel">
        <h3>{{ selectedModelId ? '编辑模型' : '新增模型' }}</h3>
        <div class="form-row"><label>配置名称<input v-model="form.name" required maxlength="80" placeholder="例如：团队知识助手" /></label>
          <label>模型名称<input v-model="form.model_name" required maxlength="120" placeholder="例如：deepseek-chat" /></label></div>
        <label>API 根地址<input v-model="form.base_url" required type="url" placeholder="https://api.example.com/v1" /></label>
        <label>API Key（编辑时留空表示不修改）<input v-model="form.api_key" type="password" autocomplete="new-password" placeholder="仅发送给所配置的模型接口" /></label>
        <div class="toolbar"><label v-if="selectedModelId"><input v-model="form.clear_api_key" type="checkbox" /> 清除已保存密钥</label>
          <label><input v-model="form.is_active" type="checkbox" /> 设为当前模型</label></div>
        <p class="muted">密钥在服务器端加密保存，页面不会回显。支持 HTTPS 接口，以及本机 HTTP 模型服务。</p>
        <button class="primary" :disabled="busy">保存模型配置</button>
      </form>
    </section>
    <section v-if="!status.configured" class="panel agent-empty"><h2>尚未配置模型</h2><p>请管理员在“模型配置”中添加兼容工具调用的模型，然后开始对话。</p></section>
    <div v-else class="agent-layout">
      <aside class="panel agent-sidebar"><button class="primary" @click="newConversation">＋ 新对话</button>
        <p class="muted">新会话模型：{{ status.model }}<br />已有会话沿用创建时的模型。</p>
        <div v-for="item in conversations" :key="item.id" class="agent-history" :class="{ active: item.id === conversationId }">
          <button @click="openConversation(item.id)">{{ item.title }}</button><button class="agent-remove" title="删除会话" @click="removeConversation(item.id)">×</button>
        </div>
      </aside>
      <section class="panel agent-chat">
        <div class="agent-messages">
          <div v-if="!messages.length" class="agent-welcome"><h2>从真实问题开始</h2><p>例如：“查找近期反光导致漏检的问题，归纳有效方案和仍需验证的条件。”</p></div>
          <article v-for="(item, index) in messages" :key="item.id || index" class="agent-message" :class="item.role">
            <b>{{ item.role === 'user' ? '我' : 'Agent' }}</b><p>{{ item.content }}</p>
            <div v-if="item.sources?.length" class="agent-sources"><span class="muted">依据：</span><button v-for="source in item.sources" :key="`${source.type}-${source.id}`" class="agent-source" @click="emit('openSource', source)">{{ source.type === 'issue' ? '问题' : source.type === 'project' ? '项目' : '知识' }} #{{ source.id }} · {{ source.title }}</button></div>
            <div v-for="action in item.actions || []" :key="action.id" class="agent-draft"><b>待确认 · 问题 #{{ action.draft.issue_id }} · {{ action.draft.event_type }}</b><p>{{ action.draft.content }}</p>
              <button v-if="action.status === 'pending'" class="primary" @click="apply(action)">确认写入</button><span v-else class="muted">{{ action.status === 'applied' ? '已写入' : '已处理' }}</span></div>
            <details v-if="item.trace?.length"><summary class="muted">工具调用记录</summary><span v-for="(step, i) in item.trace" :key="i" class="pill">{{ step.tool }} · {{ step.status }}</span></details>
          </article>
          <p v-if="busy" class="muted">Agent 正在检索并整理…</p>
        </div>
        <form class="agent-compose" @submit.prevent="send"><textarea v-model="prompt" :disabled="busy" maxlength="4000" placeholder="描述你希望 Agent 检索或分析的问题…" @keydown.ctrl.enter.prevent="send" /><div><span class="muted">对话与检索到的业务资料会发送至当前第三方模型。Ctrl + Enter 发送。</span><button class="primary" :disabled="busy || !prompt.trim()">发送</button></div></form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.agent-page{display:grid;gap:12px}.agent-alert,.agent-notice{padding:10px 14px;border-radius:9px;margin:0}.agent-alert{background:#fceff0;color:#a53d4c}.agent-notice{background:#e9f7f3;color:#287c69}.agent-settings{padding:16px}.agent-settings .panel-head{margin:-16px -16px 16px}.agent-models{display:grid;gap:8px;margin-bottom:12px}.agent-model{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:12px;background:#f5f7ff;border:1px solid var(--line);border-radius:9px}.agent-model p{margin:5px 0 0;overflow-wrap:anywhere}.agent-config{margin-top:18px;max-width:800px}.agent-config h3{margin:0}.agent-config .toolbar label{display:flex;align-items:center;gap:6px}.agent-empty{padding:24px}.agent-layout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:16px;min-height:560px}.agent-sidebar{padding:14px}.agent-sidebar>.primary{width:100%}.agent-sidebar>p{font-size:12px}.agent-history{display:flex;align-items:center;border-radius:8px;margin-bottom:4px}.agent-history.active,.agent-history:hover{background:#eaf0ff}.agent-history button{background:none;border:0;cursor:pointer;color:var(--text)}.agent-history button:first-child{text-align:left;padding:10px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.agent-remove{font-size:20px;color:var(--muted)!important}.agent-chat{display:flex;flex-direction:column;min-width:0;min-height:560px}.agent-messages{flex:1;padding:18px;display:grid;align-content:start;gap:14px;max-height:65vh;overflow:auto}.agent-welcome{padding:42px 18px;text-align:center;color:var(--muted)}.agent-welcome h2{color:var(--text)}.agent-message{max-width:90%;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#fff}.agent-message.user{justify-self:end;background:#edf2ff}.agent-message p{white-space:pre-wrap;line-height:1.6;margin:8px 0}.agent-sources{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.agent-source{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid #ccd7f7;border-radius:16px;background:#f5f7ff;color:#3152bd;padding:4px 8px;cursor:pointer}.agent-draft{margin-top:12px;padding:12px;border:1px solid #cbd7ff;border-radius:8px;background:#f7f9ff}.agent-draft .primary{font-size:12px}.agent-message details{margin-top:10px}.agent-message details .pill{margin:5px 5px 0 0}.agent-compose{border-top:1px solid var(--line);padding:14px}.agent-compose textarea{width:100%;min-height:85px;resize:vertical;padding:10px;border:1px solid var(--line);border-radius:8px;color:var(--text)}.agent-compose>div{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:8px;font-size:12px}@media(max-width:760px){.agent-layout{grid-template-columns:1fr}.agent-sidebar{max-height:180px;overflow:auto}.agent-model{display:block}.agent-message{max-width:100%}}
</style>
