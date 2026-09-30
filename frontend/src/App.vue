<script setup>
import { computed, onMounted, ref } from 'vue'
import StatusPill from './components/StatusPill.vue'
import IssueTable from './components/IssueTable.vue'
import EventTimeline from './components/EventTimeline.vue'
import IssueCommunication from './components/IssueCommunication.vue'
import ProjectCollaboration from './components/ProjectCollaboration.vue'
import PeopleManagement from './components/PeopleManagement.vue'

const baseNav = [
  ['workbench', '我的工作台'], ['projects', '项目'], ['issues', '问题'],
  ['stats', '统计趋势'], ['retro', '项目复盘'], ['knowledge', '知识库'], ['people', '人员与沟通'],
]
const issueRetroFields = [
  ['phenomenon', '问题现象'], ['impact', '问题影响'], ['process_summary', '处理过程'],
  ['root_cause', '根本原因'], ['final_solution', '最终解决办法'],
  ['validation_result', '验证结果'], ['lessons', '经验教训'], ['prevention', '预防措施'],
]
const projectRetroFields = [
  ['summary', '项目结果'], ['key_problems', '重点问题'], ['delay_analysis', '延期分析'],
  ['lessons', '经验总结'], ['improvements', '后续改进'], ['knowledge_summary', '知识沉淀'],
]
const knowledgeFields = [
  ['title', '标题'], ['scene', '场景'], ['problem', '问题'], ['root_cause', '根因'],
  ['attempts_summary', '尝试过程'], ['final_solution', '最终方案'], ['validation', '验证结果'],
  ['lessons', '经验教训'], ['prevention', '预防措施'], ['applicability', '适用/不适用条件'], ['tags', '标签'],
]

const config = ref(null)
const users = ref([])
const authUser = ref(null)
const authMode = ref('loading')
const authForm = ref({ name: '', password: '' })
const passwordForm = ref({ current_password: '', new_password: '' })
const adminUsers = ref([])
const roles = ref([])
const availablePermissions = ref([])
const roleForm = ref({ id: null, name: '', description: '', permissions: [] })
const projects = ref([])
const userId = ref(null)
const page = ref('workbench')
const loading = ref(true)
const error = ref('')
const message = ref('')
const modal = ref('')
const workbench = ref(null)
const issues = ref([])
const stats = ref(null)
const knowledge = ref([])
const projectRetro = ref(null)
const selectedRetroProject = ref('')
const projectDetail = ref(null)
const issueDetail = ref(null)
const knowledgeDetail = ref(null)
const issueTab = ref('timeline')
const issueFilters = ref({ project_id: '', issue_type: '', priority: '', status: '', q: '', delayed_only: false })
const knowledgeFilters = ref({ q: '', issue_type: '', confidence_state: '' })
const statFilters = ref({ project_id: '', days: '30' })
const userForm = ref({ id: null, name: '', role_id: null, team_id: '', scope: 'self', scope_id: '', password: '', active: true })
const projectForm = ref({ name: '', manager_id: '', current_stage: '需求确认', planned_completion_date: '', description: '' })
const projectEdit = ref({ current_stage: '', planned_completion_date: '' })
const issueForm = ref({ project_id: '', issue_type: '成像', description: '', priority: '重要不紧急', owner_id: '', planned_close_date: '', close_standard: '' })
const issueCore = ref({ status: '', priority: '', owner_id: '', planned_close_date: '', close_standard: '', delay_reason: '' })
const eventForm = ref({ event_type: '进展反馈', outcome: '', content: '' })
const issueRetroValues = ref({})
const projectRetroValues = ref({})
const knowledgeValues = ref({})
const createFiles = ref([])
const eventFiles = ref([])
const organization = ref({ departments: [], teams: [] })
const orgForm = ref({ department: '', team: '', department_id: '' })
const roleAssignments = ref([])
const roleUser = ref(null)

const currentUser = computed(() => authUser.value)
const nav = computed(() => [...baseNav, ...(can('users.manage') || can('roles.manage') || can('org.manage') ? [['admin', '用户与角色']] : [])])
function can(permission) { return authUser.value?.permissions?.includes(permission) }
const statsMax = computed(() => Math.max(1, ...(stats.value?.trend || []).flatMap((day) => [day.created, day.closed])))
const evidenceCount = computed(() => (issueDetail.value?.events || []).reduce((count, event) => count + event.attachments.length, 0))

async function api(url, options = {}) {
  const response = await fetch(url, options)
  if (response.status === 401 && !url.startsWith('/api/auth/')) {
    authUser.value = null
    authMode.value = 'login'
  }
  if (!response.ok) {
    let detail = await response.text()
    try { detail = JSON.parse(detail).detail || detail } catch { /* use response text */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return response.json()
}

function jsonOptions(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

let messageTimer
function toast(text) {
  message.value = text
  clearTimeout(messageTimer)
  messageTimer = setTimeout(() => { message.value = '' }, 2500)
}

async function act(task) {
  try { await task() } catch (cause) { toast(`操作失败：${cause.message}`) }
}

function localDateAfter(days) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function query(values) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value === true ? 'true' : value)
  return params.toString()
}

async function refreshProjects() { projects.value = await api('/api/projects') }

async function navigate(target) {
  page.value = target
  loading.value = true
  error.value = ''
  try {
    if (target === 'workbench') workbench.value = await api(`/api/workbench?owner_id=${userId.value}`)
    if (target === 'projects') await refreshProjects()
    if (target === 'issues') await filterIssues()
    if (target === 'stats') await refreshStats()
    if (target === 'retro') { await refreshProjects(); projectRetro.value = null; selectedRetroProject.value = '' }
    if (target === 'knowledge') await filterKnowledge()
    if (target === 'admin') await refreshAdmin()
  } catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}

async function initialize() {
  try {
    const status = await api('/api/auth/status')
    if (status.setup_required) { authMode.value = 'setup'; loading.value = false; return }
    try { authUser.value = await api('/api/auth/me') }
    catch { authMode.value = 'login'; loading.value = false; return }
    await loadApp()
  } catch (cause) { error.value = `启动失败：${cause.message}`; loading.value = false }
}
onMounted(initialize)

async function loadApp() {
  ;[config.value, users.value, projects.value] = await Promise.all([
    api('/api/config'), api('/api/users'), api('/api/projects'),
  ])
  userId.value = authUser.value.id
  authMode.value = 'ready'
  await navigate('workbench')
}

async function signIn() { await act(async () => {
  authUser.value = await api('/api/auth/login', jsonOptions('POST', authForm.value))
  authForm.value.password = ''
  await loadApp()
}) }
async function setupAdmin() { await act(async () => {
  authUser.value = await api('/api/auth/setup', jsonOptions('POST', { password: authForm.value.password }))
  authForm.value.password = ''
  await loadApp()
}) }
async function signOut() { await act(async () => {
  await api('/api/auth/logout', { method: 'POST' })
  authUser.value = null; authMode.value = 'login'; modal.value = ''
}) }
async function changePassword() { await act(async () => {
  await api('/api/auth/password', jsonOptions('POST', passwordForm.value))
  passwordForm.value = { current_password: '', new_password: '' }
  closeModal(); toast('密码已修改')
}) }
async function refreshAdmin() {
  if (can('users.manage')) adminUsers.value = await api('/api/admin/users')
  if (can('users.manage') || can('roles.manage')) {
    ;[roles.value, availablePermissions.value] = await Promise.all([
      api('/api/admin/roles'), api('/api/admin/permissions'),
    ])
  }
  if (can('org.manage')) {
    ;[organization.value.departments, organization.value.teams] = await Promise.all([api('/api/org/departments'), api('/api/org/teams')])
  }
}
async function addDepartment() { await act(async () => { await api('/api/org/departments', jsonOptions('POST', { name: orgForm.value.department })); orgForm.value.department = ''; await refreshAdmin() }) }
async function addTeam() { await act(async () => { await api('/api/org/teams', jsonOptions('POST', { name: orgForm.value.team, department_id: Number(orgForm.value.department_id) })); orgForm.value.team = ''; await refreshAdmin() }) }
function openRoleAssignments(user) { roleUser.value = user; roleAssignments.value = user.roles.map((item) => ({ role_id: item.role_id, scope: item.scope, scope_id: item.scope_id || '' })); modal.value = 'roleAssignments' }
function addRoleAssignment() { roleAssignments.value.push({ role_id: roles.value[0]?.id, scope: 'self', scope_id: '' }) }
async function saveRoleAssignments() { await act(async () => { await api(`/api/admin/users/${roleUser.value.id}/roles`, jsonOptions('PUT', roleAssignments.value.map((item) => ({ role_id: Number(item.role_id), scope: item.scope, scope_id: ['self','all'].includes(item.scope) ? null : item.scope_id ? Number(item.scope_id) : null })))); await refreshAdmin(); authUser.value = await api('/api/auth/me'); closeModal(); toast('授权已保存') }) }
function openUserCreate() {
  const member = roles.value.find((role) => role.name === '团队成员')
  userForm.value = { id: null, name: '', role_id: member?.id || roles.value[0]?.id, team_id: '', scope: 'self', scope_id: '', password: '', active: true }
  modal.value = 'userEdit'
}
function openUserEdit(user) {
  userForm.value = { id: user.id, name: user.name, role_id: user.role_id, team_id: user.team_id || '', scope: user.roles?.[0]?.scope || 'self', scope_id: user.roles?.[0]?.scope_id || '', password: '', active: user.active }
  modal.value = 'userEdit'
}
function openRoleEdit(role = null) {
  roleForm.value = role ? { id: role.id, name: role.name, description: role.description, permissions: [...role.permissions] }
    : { id: null, name: '', description: '', permissions: [] }
  modal.value = 'roleEdit'
}
function openProjectCreate() {
  projectForm.value = { name: '', manager_id: userId.value, current_stage: config.value.stages[0], planned_completion_date: '', description: '' }
  modal.value = 'projectCreate'
}
function openIssueCreate() {
  if (!projects.value.length) return toast('请先创建项目')
  issueForm.value = { project_id: projects.value[0].id, issue_type: config.value.issue_types[0], description: '', priority: '重要不紧急', owner_id: userId.value, planned_close_date: localDateAfter(3), close_standard: '' }
  createFiles.value = []
  modal.value = 'issueCreate'
}
function closeModal() { modal.value = ''; projectDetail.value = null; issueDetail.value = null; knowledgeDetail.value = null }
function setCreateFiles(event) { createFiles.value = Array.from(event.target.files || []) }
function setEventFiles(event) { eventFiles.value = Array.from(event.target.files || []) }

async function saveUser() { await act(async () => {
  const form = { ...userForm.value, role_id: Number(userForm.value.role_id), team_id: userForm.value.team_id ? Number(userForm.value.team_id) : null, scope_id: userForm.value.scope_id ? Number(userForm.value.scope_id) : null }
  const ownPasswordReset = form.id === userId.value && Boolean(form.password)
  if (form.id) {
    const id = form.id; delete form.id
    delete form.scope; delete form.scope_id
    if (!form.password) delete form.password
    await api(`/api/admin/users/${id}`, jsonOptions('PATCH', form))
  } else {
    delete form.id
    await api('/api/users', jsonOptions('POST', form))
  }
  if (ownPasswordReset) {
    authUser.value = null; authMode.value = 'login'
    closeModal(); toast('密码已修改，请重新登录')
    return
  }
  if (userForm.value.id === userId.value) authUser.value = await api('/api/auth/me')
  users.value = await api('/api/users')
  closeModal(); toast('用户已保存')
  if (can('users.manage') || can('roles.manage')) await refreshAdmin()
  else await navigate('workbench')
}) }
async function saveRole() { await act(async () => {
  const form = { ...roleForm.value }; const id = form.id; delete form.id
  await api(id ? `/api/admin/roles/${id}` : '/api/admin/roles', jsonOptions(id ? 'PATCH' : 'POST', form))
  authUser.value = await api('/api/auth/me')
  users.value = await api('/api/users')
  closeModal(); toast('角色已保存')
  if (can('users.manage') || can('roles.manage')) await refreshAdmin()
  else await navigate('workbench')
}) }
async function deleteRole(role) { await act(async () => {
  if (!window.confirm(`删除角色“${role.name}”？`)) return
  await api(`/api/admin/roles/${role.id}`, { method: 'DELETE' })
  await refreshAdmin(); toast('角色已删除')
}) }

async function createProject() { await act(async () => {
  await api('/api/projects', jsonOptions('POST', { ...projectForm.value, manager_id: Number(projectForm.value.manager_id), description: projectForm.value.description || null }))
  await refreshProjects()
  closeModal(); toast('项目已创建'); await navigate('projects')
}) }

async function createIssue() { await act(async () => {
  const payload = { ...issueForm.value, project_id: Number(issueForm.value.project_id), owner_id: Number(issueForm.value.owner_id), created_by_id: userId.value, status: '待处理', close_standard: issueForm.value.close_standard || null }
  const created = await api('/api/issues', jsonOptions('POST', payload))
  if (createFiles.value.length) {
    const data = new FormData()
    data.append('actor_id', String(userId.value))
    data.append('attachment_role', '问题证据')
    createFiles.value.forEach((file) => data.append('files', file))
    await api(`/api/issues/${created.id}/creation-attachments`, { method: 'POST', body: data })
  }
  await refreshProjects()
  closeModal(); toast('问题已记录'); await navigate(page.value)
}) }

async function openProject(id) { await act(async () => {
  projectDetail.value = await api(`/api/projects/${id}`)
  projectEdit.value = { current_stage: projectDetail.value.current_stage, planned_completion_date: projectDetail.value.planned_completion_date }
  modal.value = 'project'
}) }

async function saveProject() { await act(async () => {
  await api(`/api/projects/${projectDetail.value.id}`, jsonOptions('PATCH', { actor_id: userId.value, ...projectEdit.value }))
  closeModal(); toast('项目已更新'); await navigate('projects')
}) }

async function filterIssues() { issues.value = await api(`/api/issues?${query(issueFilters.value)}`) }
async function refreshStats() { stats.value = await api(`/api/stats?${query(statFilters.value)}`) }
async function filterKnowledge() { knowledge.value = await api(`/api/knowledge?${query(knowledgeFilters.value)}`) }

async function loadProjectRetro() { await act(async () => {
  if (!selectedRetroProject.value) { projectRetro.value = null; return }
  projectRetro.value = await api(`/api/projects/${selectedRetroProject.value}/retrospective`)
  projectRetroValues.value = Object.fromEntries(projectRetroFields.map(([key]) => [key, projectRetro.value.retrospective[key] || '']))
}) }

async function saveProjectRetro() { await act(async () => {
  await api(`/api/projects/${selectedRetroProject.value}/retrospective`, jsonOptions('PATCH', { actor_id: userId.value, values: projectRetroValues.value, confirm: true }))
  toast('项目复盘已保存'); await loadProjectRetro()
}) }

async function regenerateProjectRetro() { await act(async () => {
  await api(`/api/projects/${selectedRetroProject.value}/retrospective/regenerate`, { method: 'POST' })
  toast('已按最新问题自动更新'); await loadProjectRetro()
}) }

async function openIssue(id, tab = 'timeline') { await act(async () => {
  issueDetail.value = await api(`/api/issues/${id}`)
  issueTab.value = tab
  issueCore.value = {
    status: issueDetail.value.status, priority: issueDetail.value.priority, owner_id: issueDetail.value.owner_id,
    planned_close_date: issueDetail.value.planned_close_date, close_standard: issueDetail.value.close_standard || '',
    delay_reason: issueDetail.value.delay_reason || '',
  }
  eventForm.value = { event_type: '进展反馈', outcome: '', content: '' }
  eventFiles.value = []
  issueRetroValues.value = Object.fromEntries(issueRetroFields.map(([key]) => [key, issueDetail.value.retrospective[key] || '']))
  modal.value = 'issue'
}) }

async function addEvent() { await act(async () => {
  const data = new FormData()
  data.append('actor_id', String(userId.value))
  data.append('event_type', eventForm.value.event_type)
  data.append('content', eventForm.value.content)
  if (eventForm.value.outcome) data.append('outcome', eventForm.value.outcome)
  const roles = { '进展反馈': '问题证据', '解决办法': '方案说明', '验证结果': '验证证据', '根因判断': '问题证据' }
  data.append('attachment_role', roles[eventForm.value.event_type] || '其他')
  eventFiles.value.forEach((file) => data.append('files', file))
  const id = issueDetail.value.id
  await api(`/api/issues/${id}/events`, { method: 'POST', body: data })
  toast('进展已记录并自动进入复盘'); await openIssue(id)
}) }

async function saveIssueCore() { await act(async () => {
  const id = issueDetail.value.id
  const updated = await api(`/api/issues/${id}`, jsonOptions('PATCH', {
    actor_id: userId.value, ...issueCore.value, owner_id: Number(issueCore.value.owner_id),
    close_standard: issueCore.value.close_standard || null, delay_reason: issueCore.value.delay_reason || null,
  }))
  toast(updated.meaningful_changes ? `已记录${updated.meaningful_changes}项有效变更` : '没有有效变化，不产生历史噪声')
  await openIssue(id)
}) }

async function saveIssueRetro() { await act(async () => {
  const id = issueDetail.value.id
  await api(`/api/issues/${id}/retrospective`, jsonOptions('PATCH', { actor_id: userId.value, values: issueRetroValues.value, confirm: true }))
  toast('复盘已确认，人工修订已留痕'); await openIssue(id, 'retro')
}) }

async function regenerateIssueRetro() { await act(async () => {
  const id = issueDetail.value.id
  await api(`/api/issues/${id}/retrospective/regenerate`, { method: 'POST' })
  toast('已重新提取，人工锁定字段保留'); await openIssue(id, 'retro')
}) }

async function openKnowledge(id) { await act(async () => {
  knowledgeDetail.value = await api(`/api/knowledge/${id}`)
  knowledgeValues.value = Object.fromEntries(knowledgeFields.map(([key]) => [key, knowledgeDetail.value[key] || '']))
  knowledgeValues.value.confidence_state = knowledgeDetail.value.confidence_state
  modal.value = 'knowledge'
}) }

async function saveKnowledge() { await act(async () => {
  await api(`/api/knowledge/${knowledgeDetail.value.id}`, jsonOptions('PATCH', { actor_id: userId.value, values: knowledgeValues.value }))
  closeModal(); toast('知识案例已保存'); await navigate('knowledge')
}) }

function barMax(items) { return Math.max(1, ...items.map((item) => item.count)) }
function date(value) { return value ? String(value).slice(0, 10) : '' }
function downloadAgentExport() { window.open('/api/knowledge/export/agent', '_blank', 'noopener') }
</script>

<template>
  <header>
    <div class="brand"><img class="logo" src="/brand-mark.svg" alt="" width="40" height="40" /><div><b>工业视觉项目与知识平台</b><small>问题驱动 · 过程留痕 · 自动复盘 · 经验沉淀</small></div></div>
    <nav v-if="authUser"><button v-for="[key, label] in nav" :key="key" :class="{ active: page === key }" @click="navigate(key)">{{ label }}</button></nav>
    <div class="userbox" v-if="currentUser"><span>{{ currentUser.name }} · {{ currentUser.role }}</span><button v-if="can('issues.write')" class="primary" @click="openIssueCreate">＋ 新增问题</button><button class="secondary" @click="modal = 'passwordChange'">修改密码</button><button class="secondary" @click="signOut">退出</button></div>
  </header>

  <main>
    <div v-if="authMode === 'setup' || authMode === 'login'" class="auth-card panel">
      <h1>{{ authMode === 'setup' ? '首次设置管理员密码' : '登录' }}</h1>
      <p class="muted">{{ authMode === 'setup' ? '请在服务器本机完成设置。密码至少 12 个字符，设置后由管理员为其他成员分配账户。' : '使用管理员分配的姓名和密码登录。' }}</p>
      <form class="form" @submit.prevent="authMode === 'setup' ? setupAdmin() : signIn()">
        <label v-if="authMode === 'login'">姓名<input v-model="authForm.name" autocomplete="username" required /></label>
        <label>密码<input v-model="authForm.password" type="password" :autocomplete="authMode === 'setup' ? 'new-password' : 'current-password'" :minlength="authMode === 'setup' ? 12 : 1" required /></label>
        <button class="primary">{{ authMode === 'setup' ? '设置并登录' : '登录' }}</button>
      </form>
    </div>
    <div v-else-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="empty">{{ error }}</div>

    <template v-else-if="page === 'workbench' && workbench">
      <div class="page-head"><div><h1>{{ currentUser?.name }}的工作台</h1><p>只看需要你处理的事，项目管理和复盘由系统自动生成。</p></div><div class="toolbar"><button v-if="can('users.manage')" class="secondary" @click="navigate('admin')">用户与角色</button><button v-if="can('projects.write')" class="secondary" @click="openProjectCreate">＋ 项目</button></div></div>
      <div class="cards"><div v-for="[label, count] in [['我的未关闭', workbench.counts.all], ['紧急重要', workbench.counts.critical], ['阻塞', workbench.counts.blocked], ['本周到期', workbench.counts.due_week], ['已延期', workbench.counts.delayed]]" :key="label" class="card metric"><span>{{ label }}</span><b>{{ count }}</b></div></div>
      <div class="panel"><div class="panel-head"><h2>我的问题</h2><span class="muted">优先显示紧急 / 阻塞 / 临期</span></div><IssueTable :issues="workbench.issues" @open="openIssue" /></div>
    </template>

    <template v-else-if="page === 'projects'">
      <div class="page-head"><div><h1>项目总览</h1><p>项目状态由未关闭问题自动推导，减少重复维护。</p></div><button v-if="can('projects.write')" class="primary" @click="openProjectCreate">＋ 新建项目</button></div>
      <div class="panel table-wrap"><table><thead><tr><th>项目</th><th>负责人</th><th>阶段</th><th>总体状态</th><th>计划完成</th><th>未关闭</th><th>紧急重要</th><th>阻塞</th><th>延期</th></tr></thead><tbody>
        <tr v-for="project in projects" :key="project.id" class="clickable" @click="openProject(project.id)"><td><b>{{ project.name }}</b></td><td>{{ project.manager_name }}</td><td><StatusPill :value="project.current_stage" /></td><td><StatusPill :value="project.overall_status" /></td><td>{{ date(project.planned_completion_date) }}</td><td>{{ project.counts.open }}</td><td>{{ project.counts.critical }}</td><td>{{ project.counts.blocked }}</td><td>{{ project.counts.delayed }}</td></tr>
        <tr v-if="!projects.length"><td colspan="9" class="empty">暂无项目</td></tr>
      </tbody></table></div>
    </template>

    <template v-else-if="page === 'issues'">
      <div class="page-head"><div><h1>全部问题</h1><p>所有任务、风险和现场异常统一为“问题”，一行一个待解决事项。</p></div></div>
      <form class="toolbar filters" @submit.prevent="act(filterIssues)"><select v-model="issueFilters.project_id" aria-label="筛选项目"><option value="">全部项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select><select v-model="issueFilters.issue_type" aria-label="筛选类型"><option value="">全部类型</option><option v-for="item in config.issue_types" :key="item">{{ item }}</option></select><select v-model="issueFilters.priority" aria-label="筛选优先级"><option value="">全部优先级</option><option v-for="item in config.priorities" :key="item">{{ item }}</option></select><select v-model="issueFilters.status" aria-label="筛选状态"><option value="">全部状态</option><option v-for="item in config.issue_statuses" :key="item">{{ item }}</option></select><input v-model="issueFilters.q" placeholder="搜索问题" /><label><input v-model="issueFilters.delayed_only" type="checkbox" /> 仅延期</label><button class="secondary">筛选</button></form>
      <div class="panel"><IssueTable :issues="issues" @open="openIssue" /></div>
    </template>

    <template v-else-if="page === 'stats' && stats">
      <div class="page-head"><div><h1>统计趋势</h1><p>观察问题新增/关闭速度、延期率和问题结构。</p></div><div class="toolbar"><select v-model="statFilters.project_id" aria-label="统计项目" @change="act(refreshStats)"><option value="">全部项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select><select v-model="statFilters.days" aria-label="统计天数" @change="act(refreshStats)"><option value="7">7天</option><option value="30">30天</option><option value="90">90天</option></select></div></div>
      <div class="cards"><div v-for="[label, count] in [['问题总数', stats.summary.total], ['未关闭', stats.summary.open], ['紧急重要', stats.summary.critical], ['阻塞', stats.summary.blocked], ['延期率', `${stats.summary.delay_rate}%`]]" :key="label" class="card metric"><span>{{ label }}</span><b>{{ count }}</b></div></div>
      <div class="grid2"><div class="panel"><div class="panel-head"><h2>新增 / 关闭趋势</h2><span><i style="color:var(--blue)">■</i>新增　<i style="color:var(--cyan)">■</i>关闭</span></div><div class="trend"><div v-for="day in stats.trend" :key="day.date" class="day" :title="`${day.date} 新增${day.created} 关闭${day.closed}`"><i class="c" :style="{ height: `${Math.max(2, day.created / statsMax * 100)}%` }"></i><i class="x" :style="{ height: `${Math.max(2, day.closed / statsMax * 100)}%` }"></i></div></div></div><div class="panel"><div class="panel-head"><h2>问题类型分布</h2></div><div class="bars"><div v-for="item in stats.types" :key="item.name" class="bar-row"><span>{{ item.name }}</span><div class="bar-bg"><div class="bar-fill" :style="{ width: `${item.count / barMax(stats.types) * 100}%` }"></div></div><b>{{ item.count }}</b></div><div v-if="!stats.types.length" class="empty">暂无数据</div></div></div></div>
      <div class="panel"><div class="panel-head"><h2>主要延期原因</h2></div><div class="bars"><div v-for="item in stats.delay_reasons" :key="item.name" class="bar-row"><span>{{ item.name }}</span><div class="bar-bg"><div class="bar-fill" :style="{ width: `${item.count / barMax(stats.delay_reasons) * 100}%` }"></div></div><b>{{ item.count }}</b></div><div v-if="!stats.delay_reasons.length" class="empty">暂无数据</div></div></div>
    </template>

    <template v-else-if="page === 'retro'">
      <div class="page-head"><div><h1>项目复盘</h1><p>问题复盘在处理过程中自动积累，项目复盘直接汇总。</p></div><select v-model="selectedRetroProject" aria-label="选择复盘项目" @change="loadProjectRetro"><option value="">选择项目</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></div>
      <div v-if="!projectRetro" class="empty">请选择一个项目</div>
      <template v-else><div class="cards"><div v-for="[label, count] in [['未关闭', projectRetro.project.counts.open], ['紧急重要', projectRetro.project.counts.critical], ['阻塞', projectRetro.project.counts.blocked], ['延期', projectRetro.project.counts.delayed], ['阶段', projectRetro.project.current_stage]]" :key="label" class="card metric"><span>{{ label }}</span><b>{{ count }}</b></div></div><div class="panel"><div class="panel-head"><h2>自动生成 + 人工修订</h2><div v-if="can('projects.write')" class="toolbar"><button class="secondary" @click="regenerateProjectRetro">重新自动提取</button><button class="primary" @click="saveProjectRetro">保存并确认</button></div></div><div class="retro-fields"><div v-for="[key, label] in projectRetroFields" :key="key" class="retro-field"><label>{{ label }}<span :class="{ locked: projectRetro.retrospective.locked_fields.includes(key) }">{{ projectRetro.retrospective.locked_fields.includes(key) ? '人工内容已锁定' : '自动提取' }}</span></label><textarea v-model="projectRetroValues[key]" :aria-label="label" :readonly="!can('projects.write')"></textarea></div></div></div></template>
    </template>

    <template v-else-if="page === 'knowledge'">
      <div class="page-head"><div><h1>工业视觉知识库</h1><p>从真实问题处理过程自动形成可复用的案例。</p></div><button class="secondary" @click="downloadAgentExport">Agent结构化导出</button></div>
      <form class="toolbar filters" @submit.prevent="act(filterKnowledge)"><input v-model="knowledgeFilters.q" placeholder="搜索问题/根因/方案/标签" /><select v-model="knowledgeFilters.issue_type" aria-label="知识类型"><option value="">全部类型</option><option v-for="item in config.issue_types" :key="item">{{ item }}</option></select><select v-model="knowledgeFilters.confidence_state" aria-label="知识可信度"><option value="">全部可信度</option><option v-for="item in config.knowledge_states" :key="item">{{ item }}</option></select><button class="secondary">搜索</button></form>
      <div class="panel"><div v-for="item in knowledge" :key="item.id" class="knowledge-card" @click="openKnowledge(item.id)"><h3>{{ item.title }} <StatusPill :value="item.confidence_state" /></h3><p><b>根因：</b>{{ (item.root_cause || '').slice(0, 180) }}</p><p><b>最终方案：</b>{{ (item.final_solution || '').slice(0, 180) }}</p><p class="muted">{{ item.project_name }} · 证据{{ item.evidence_count }}份 · {{ item.tags }}</p></div><div v-if="!knowledge.length" class="empty">知识案例会随着问题处理自动产生</div></div>
    </template>

    <template v-else-if="page === 'people'"><PeopleManagement :api="api" :current-user="currentUser" :permissions="currentUser?.permissions || []" @open-issue="openIssue" /></template>

    <template v-else-if="page === 'admin'">
      <div class="page-head"><div><h1>用户与角色</h1><p>停用用户会保留项目、问题和操作历史；内置角色不可修改。</p></div></div>
      <div v-if="can('users.manage')" class="panel">
        <div class="panel-head"><h2>用户</h2><button class="primary" @click="openUserCreate">＋ 新增用户</button></div>
        <div class="table-wrap"><table><thead><tr><th>姓名 / 登录名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="user in adminUsers" :key="user.id"><td>{{ user.name }}</td><td>{{ user.roles?.map((item) => `${item.name} · ${item.scope}${item.scope_id ? ' #'+item.scope_id : ''}`).join('、') || user.role }}</td><td>{{ !user.active ? '停用' : user.has_password ? '启用' : '待设置密码' }}</td><td><button class="secondary" @click="openUserEdit(user)">编辑 / 重置密码</button> <button class="secondary" @click="openRoleAssignments(user)">多角色授权</button></td></tr>
        </tbody></table></div>
      </div>
      <div v-if="can('roles.manage')" class="panel">
        <div class="panel-head"><h2>角色与权限</h2><button class="primary" @click="openRoleEdit()">＋ 新增角色</button></div>
        <div class="table-wrap"><table><thead><tr><th>角色</th><th>说明</th><th>权限</th><th>人数</th><th>操作</th></tr></thead><tbody>
          <tr v-for="role in roles" :key="role.id"><td><b>{{ role.name }}</b><span v-if="role.is_system" class="muted"> · 内置</span></td><td>{{ role.description }}</td><td>{{ role.permissions.map((key) => availablePermissions.find((item) => item.key === key)?.label || key).join('、') || '仅查看' }}</td><td>{{ role.user_count }}</td><td><template v-if="!role.is_system"><button class="secondary" @click="openRoleEdit(role)">编辑</button> <button class="secondary danger" @click="deleteRole(role)">删除</button></template></td></tr>
        </tbody></table></div>
      </div>
      <div v-if="can('org.manage')" class="grid2"><section class="panel"><h2>部门</h2><p v-for="item in organization.departments" :key="item.id">{{ item.name }} · #{{ item.id }}</p><form class="toolbar" @submit.prevent="addDepartment"><input v-model="orgForm.department" placeholder="新部门名称" required /><button class="secondary">新增</button></form></section><section class="panel"><h2>团队</h2><p v-for="item in organization.teams" :key="item.id">{{ item.name }} · {{ organization.departments.find((d) => d.id === item.department_id)?.name }}</p><form class="toolbar" @submit.prevent="addTeam"><input v-model="orgForm.team" placeholder="新团队名称" required /><select v-model="orgForm.department_id" required><option value="">所属部门</option><option v-for="item in organization.departments" :key="item.id" :value="item.id">{{ item.name }}</option></select><button class="secondary">新增</button></form></section></div>
    </template>
  </main>

  <div v-if="modal" class="modal" @click.self="closeModal"><div class="modal-card"><button class="close" aria-label="关闭" @click="closeModal">×</button>
    <template v-if="modal === 'userEdit'"><h2>{{ userForm.id ? '编辑用户' : '新增用户' }}</h2><form class="form" @submit.prevent="saveUser"><label>姓名 / 登录名<input v-model="userForm.name" maxlength="80" required /></label><label>角色<select v-model.number="userForm.role_id" required><option v-for="role in roles" :key="role.id" :value="role.id">{{ role.name }}</option></select></label><label>密码{{ userForm.id ? '（留空则不修改）' : '' }}<input v-model="userForm.password" type="password" autocomplete="new-password" :required="!userForm.id" :minlength="userForm.password ? 12 : undefined" /></label><label>所属团队<select v-model="userForm.team_id"><option value="">未分配</option><option v-for="team in organization.teams" :key="team.id" :value="team.id">{{ team.name }}</option></select></label><label v-if="!userForm.id">初始授权范围<select v-model="userForm.scope"><option value="self">本人</option><option value="project">项目</option><option value="team">团队</option><option value="department">部门</option><option value="all">全局</option></select></label><label v-if="!userForm.id && !['self','all'].includes(userForm.scope)">范围编号<input v-model="userForm.scope_id" type="number" min="1" /></label><label v-if="userForm.id" class="check-row"><input v-model="userForm.active" type="checkbox" /> 启用此用户</label><button class="primary">保存用户</button></form></template>
    <template v-else-if="modal === 'roleEdit'"><h2>{{ roleForm.id ? '编辑角色' : '新增角色' }}</h2><form class="form" @submit.prevent="saveRole"><label>角色名称<input v-model="roleForm.name" maxlength="40" required /></label><label>说明<input v-model="roleForm.description" maxlength="200" /></label><div class="permission-options"><b>操作权限</b><label v-for="permission in availablePermissions" :key="permission.key" class="check-row"><input v-model="roleForm.permissions" type="checkbox" :value="permission.key" /> {{ permission.label }}</label></div><button class="primary">保存角色</button></form></template>
    <template v-else-if="modal === 'roleAssignments'"><h2>{{ roleUser?.name }} · 多角色授权</h2><p class="muted">范围可选本人、项目、团队、部门或全局；有编号时仅限指定对象。</p><form class="form" @submit.prevent="saveRoleAssignments"><div v-for="(item,index) in roleAssignments" :key="index" class="form-row"><select v-model.number="item.role_id" required><option v-for="role in roles" :key="role.id" :value="role.id">{{ role.name }}</option></select><select v-model="item.scope"><option value="self">本人</option><option value="project">项目</option><option value="team">团队</option><option value="department">部门</option><option value="all">全局</option></select><input v-if="!['self','all'].includes(item.scope)" v-model="item.scope_id" type="number" min="1" placeholder="限定编号；留空按归属" /><button class="secondary" type="button" @click="roleAssignments.splice(index,1)">移除</button></div><button type="button" class="secondary" @click="addRoleAssignment">＋ 授权</button><button class="primary" :disabled="!roleAssignments.length">保存授权</button></form></template>
    <template v-else-if="modal === 'passwordChange'"><h2>修改密码</h2><form class="form" @submit.prevent="changePassword"><label>当前密码<input v-model="passwordForm.current_password" type="password" autocomplete="current-password" required /></label><label>新密码（至少 12 个字符）<input v-model="passwordForm.new_password" type="password" autocomplete="new-password" minlength="12" required /></label><button class="primary">保存新密码</button></form></template>
    <template v-else-if="modal === 'projectCreate'"><h2>新建项目</h2><form class="form" @submit.prevent="createProject"><label>项目名称<input v-model="projectForm.name" required /></label><div class="form-row"><label>项目负责人<select v-model="projectForm.manager_id"><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select></label><label>当前阶段<select v-model="projectForm.current_stage"><option v-for="item in config.stages" :key="item">{{ item }}</option></select></label></div><label>总体计划完成时间<input v-model="projectForm.planned_completion_date" type="date" required /></label><label>项目说明<textarea v-model="projectForm.description"></textarea></label><button class="primary">创建</button></form></template>
    <template v-else-if="modal === 'issueCreate'"><h2>快速新增问题</h2><p class="muted">只填写必要信息；图片/视频可直接一起上传。</p><form class="form" @submit.prevent="createIssue"><div class="form-row"><label>项目<select v-model="issueForm.project_id"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label><label>问题类型<select v-model="issueForm.issue_type"><option v-for="item in config.issue_types" :key="item">{{ item }}</option></select></label></div><label>问题描述<textarea v-model="issueForm.description" required placeholder="把现场真正需要解决的事写清楚…"></textarea></label><div class="form-row"><label>优先级<select v-model="issueForm.priority"><option v-for="item in config.priorities" :key="item">{{ item }}</option></select></label><label>问题Owner<select v-model="issueForm.owner_id"><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select></label></div><div class="form-row"><label>计划关闭时间<input v-model="issueForm.planned_close_date" type="date" required /></label><label>关闭标准（可后补）<input v-model="issueForm.close_standard" placeholder="怎样证明问题真的解决" /></label></div><label>问题证据（可选）<input type="file" multiple accept="image/*,video/*,.log,.txt,.csv,.xlsx,.zip" @change="setCreateFiles" /></label><button class="primary">保存问题</button></form></template>
    <template v-else-if="modal === 'project' && projectDetail"><h2>{{ projectDetail.name }}</h2><div class="cards"><div v-for="[label, count] in [['状态', projectDetail.overall_status], ['阶段', projectDetail.current_stage], ['未关闭', projectDetail.counts.open], ['阻塞', projectDetail.counts.blocked], ['延期', projectDetail.counts.delayed]]" :key="label" class="card metric"><span>{{ label }}</span><b>{{ count }}</b></div></div><div v-if="can('projects.write')" class="form-row project-edit"><label>当前阶段<select v-model="projectEdit.current_stage"><option v-for="item in config.stages" :key="item">{{ item }}</option></select></label><label>计划完成时间<input v-model="projectEdit.planned_completion_date" type="date" /></label></div><button v-if="can('projects.write')" class="secondary" @click="saveProject">保存项目状态</button><h3>问题</h3><div class="table-wrap"><table><thead><tr><th>类型</th><th>问题</th><th>优先级</th><th>状态</th><th>Owner</th><th>关闭时间</th></tr></thead><tbody><tr v-for="issue in projectDetail.issues" :key="issue.id" class="clickable" @click="openIssue(issue.id)"><td><StatusPill :value="issue.issue_type" /></td><td>{{ issue.description }}</td><td><StatusPill :value="issue.priority" /></td><td><StatusPill :value="issue.status" /></td><td>{{ issue.owner_name }}</td><td>{{ date(issue.planned_close_date) }}</td></tr><tr v-if="!projectDetail.issues.length"><td colspan="6" class="empty">暂无问题</td></tr></tbody></table></div><ProjectCollaboration :project-id="projectDetail.id" :api="api" :users="users" :permissions="currentUser?.permissions || []" /></template>
    <template v-else-if="modal === 'issue' && issueDetail"><h2>{{ issueDetail.description }}</h2><p class="muted">{{ issueDetail.project_name }} · <StatusPill :value="issueDetail.issue_type" /> <StatusPill :value="issueDetail.priority" /> <StatusPill :value="issueDetail.status" /> <StatusPill v-if="issueDetail.is_delayed" :value="`延期${issueDetail.delay_days}天`" /></p><div class="tabs"><button v-for="[key, label] in [['timeline', '处理时间线'], ['communication', '沟通反馈'], ['retro', '问题复盘'], ['knowledge', '知识案例']]" :key="key" :class="{ active: issueTab === key }" @click="issueTab = key">{{ label }}</button></div>
      <div v-if="issueTab === 'timeline'" class="grid2"><div><div v-if="can('issues.write')" class="quick-event"><b>随手反馈</b><div class="form-row"><select v-model="eventForm.event_type" aria-label="反馈类型"><option v-for="item in config.event_types" :key="item">{{ item }}</option></select><select v-model="eventForm.outcome" aria-label="反馈结果"><option value="">结果（可选）</option><option v-for="item in config.event_outcomes" :key="item">{{ item }}</option></select></div><textarea v-model="eventForm.content" placeholder="进展、尝试、判断、验证结果…"></textarea><input type="file" multiple accept="image/*,video/*,.log,.txt,.csv,.xlsx,.zip" @change="setEventFiles" /><p class="file-hint">附件角色会按反馈类型自动归类。</p><button class="primary" @click="addEvent">提交反馈</button></div><EventTimeline :events="issueDetail.events" /></div><div><div v-if="can('issues.write')" class="panel"><div class="panel-head"><h2>问题属性</h2></div><div class="form issue-core"><label>状态<select v-model="issueCore.status"><option v-for="item in config.issue_statuses" :key="item">{{ item }}</option></select></label><label>优先级<select v-model="issueCore.priority"><option v-for="item in config.priorities" :key="item">{{ item }}</option></select></label><label>问题Owner<select v-model="issueCore.owner_id"><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select></label><label>计划关闭<input v-model="issueCore.planned_close_date" type="date" /></label><label>关闭标准<textarea v-model="issueCore.close_standard"></textarea></label><label>延期原因<textarea v-model="issueCore.delay_reason"></textarea></label><button class="secondary" @click="saveIssueCore">保存有意义变更</button></div></div><div class="card"><b>系统自动沉淀</b><p class="muted">当前已有 {{ issueDetail.events.length }} 条事件记录、{{ evidenceCount }} 份多模态证据。</p></div></div></div>
      <IssueCommunication v-else-if="issueTab === 'communication'" :issue-id="issueDetail.id" :api="api" :users="users" :permissions="currentUser?.permissions || []" @open-issue="openIssue" /><div v-else-if="issueTab === 'retro'" class="panel"><div class="panel-head"><h2>伴随式问题复盘</h2><div v-if="can('issues.write')" class="toolbar"><button class="secondary" @click="regenerateIssueRetro">重新自动提取</button><button class="primary" @click="saveIssueRetro">保存并确认</button></div></div><div class="retro-fields"><div v-for="[key, label] in issueRetroFields" :key="key" class="retro-field"><label>{{ label }}<span :class="{ locked: issueDetail.retrospective.locked_fields.includes(key) }">{{ issueDetail.retrospective.locked_fields.includes(key) ? '人工内容已锁定' : '自动提取' }}</span></label><textarea v-model="issueRetroValues[key]" :aria-label="label" :readonly="!can('issues.write')"></textarea></div></div></div>
      <div v-else class="card knowledge-detail"><h3>{{ issueDetail.knowledge.title }} <StatusPill :value="issueDetail.knowledge.confidence_state" /></h3><p v-for="[key, label] in knowledgeFields.filter(([key]) => key !== 'title' && key !== 'tags')" :key="key"><b>{{ label }}：</b>{{ issueDetail.knowledge[key] }}</p><p class="muted">证据 {{ issueDetail.knowledge.evidence_count }} 份 · 标签 {{ issueDetail.knowledge.tags }}</p><button v-if="can('knowledge.write')" class="secondary" @click="openKnowledge(issueDetail.knowledge.id)">编辑知识案例</button></div>
    </template>
    <template v-else-if="modal === 'knowledge' && knowledgeDetail"><h2>知识案例</h2><p><StatusPill :value="knowledgeDetail.confidence_state" /> · 证据{{ knowledgeDetail.evidence_count }}份</p><div class="form"><label v-for="[key, label] in knowledgeFields" :key="key">{{ label }}<span v-if="knowledgeDetail.locked_fields.includes(key)" class="locked">人工锁定</span><textarea v-model="knowledgeValues[key]" :readonly="!can('knowledge.write')"></textarea></label><label>可信度<select v-model="knowledgeValues.confidence_state" :disabled="!can('knowledge.write')"><option v-for="item in config.knowledge_states" :key="item">{{ item }}</option></select></label><button v-if="can('knowledge.write')" class="primary" @click="saveKnowledge">保存人工修订</button></div><h3>原始处理证据</h3><EventTimeline :events="knowledgeDetail.events" /></template>
  </div></div>
  <div id="toast" :class="{ show: message }" role="status">{{ message }}</div>
</template>
