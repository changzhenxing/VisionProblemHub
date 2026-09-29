<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ api: Function, currentUser: Object, permissions: Array })
const emit = defineEmits(['openIssue'])
const people = ref([]), overview = ref([]), selected = ref(null), skills = ref([]), notes = ref([]), actions = ref([]), notifications = ref([]), report = ref(null)
const noteForm = ref({ summary: '', actions: '', resource_request: '', growth_goal: '' }), error = ref(''), active = ref('people')
const can = (key) => props.permissions?.includes(key)
const send = (url, method, payload) => props.api(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
async function load() {
  try {
    people.value = await props.api('/api/people')
    notifications.value = await props.api('/api/notifications')
    report.value = await props.api('/api/reports/weekly')
    if (can('people.read') || can('people.manage')) overview.value = await props.api('/api/management/overview')
    await selectPerson(selected.value?.id || props.currentUser.id)
    error.value = ''
  } catch (cause) { error.value = cause.message }
}
watch(() => props.currentUser?.id, (id) => { if (id) load() }, { immediate: true })
async function selectPerson(id) {
  try {
    selected.value = await props.api(`/api/people/${id}`)
    skills.value = await props.api(`/api/people/${id}/skills`)
    try { notes.value = await props.api(`/api/people/${id}/one-on-ones`); actions.value = await props.api(`/api/people/${id}/growth-actions`) }
    catch { notes.value = []; actions.value = [] }
  } catch (cause) { error.value = cause.message }
}
async function addNote() { try { await send(`/api/people/${selected.value.id}/one-on-ones`, 'POST', noteForm.value); noteForm.value = { summary: '', actions: '', resource_request: '', growth_goal: '' }; await selectPerson(selected.value.id) } catch (cause) { error.value = cause.message } }
async function confirmNote(id) { try { await props.api(`/api/one-on-ones/${id}/confirm`, { method: 'POST' }); await selectPerson(selected.value.id) } catch (cause) { error.value = cause.message } }
async function changeSkill(item, state) { try { await send(`/api/skills/${item.id}`, 'PATCH', { state }); await selectPerson(selected.value.id) } catch (cause) { error.value = cause.message } }
async function changeAction(item, status) { try { await send(`/api/growth-actions/${item.id}`, 'PATCH', { status }); await selectPerson(selected.value.id) } catch (cause) { error.value = cause.message } }
async function readNotice(item) { try { await props.api(`/api/notifications/${item.id}/read`, { method: 'POST' }); item.read_at = new Date().toISOString(); if (item.issue_id) emit('openIssue', item.issue_id) } catch (cause) { error.value = cause.message } }
async function saveReport(confirm) { try { report.value = await send('/api/reports/weekly', 'PUT', { week_start: report.value.week_start, content: report.value.content, confirm }) } catch (cause) { error.value = cause.message } }
</script>
<template>
  <div><div class="page-head"><div><h1>人员与管理沟通</h1><p>工作事实、沟通建议与能力证据都能追溯到具体问题。</p></div></div>
    <div class="tabs"><button v-for="[key,label] in [['people','人员'],['management','沟通建议'],['notifications','提醒'],['report','我的周报']]" :key="key" :class="{active:active===key}" @click="active=key">{{ label }}</button></div>
    <p v-if="error" class="people-error">{{ error }}</p>
    <template v-if="active==='people'"><div class="toolbar"><label>人员 <select :value="selected?.id" @change="selectPerson(Number($event.target.value))"><option v-for="person in people" :key="person.id" :value="person.id">{{ person.name }}</option></select></label></div>
      <template v-if="selected"><div class="cards"><div v-for="[label,value] in [['未关闭',selected.workload.open],['紧急',selected.workload.urgent],['阻塞',selected.workload.blocked],['并行项目',selected.workload.projects],['已关闭',selected.contribution.closed_owned],['协助问题',selected.contribution.assisted_issues]]" :key="label" class="card metric"><span>{{ label }}</span><b>{{ value }}</b></div></div>
        <section class="panel"><h2>当前责任与沟通话题</h2><p v-for="item in selected.recommendations" :key="item.rule+item.issue_ids.join(',')">{{ item.text }} <button v-for="id in item.issue_ids" :key="id" class="people-link" @click="emit('openIssue',id)">#{{ id }}</button></p><p v-if="!selected.recommendations.length" class="muted">暂无需要沟通的异常</p></section>
        <div class="grid2"><section class="panel"><h2>能力证据</h2><p class="muted">规则自动建议，主管确认后生效；不形成个人排名。</p><div v-for="item in skills" :key="item.id" class="people-item"><b>{{ item.skill }} · {{ item.state }}</b><p>{{ item.evidence }}</p><button class="people-link" @click="emit('openIssue',item.issue_id)">来源问题 #{{ item.issue_id }}</button><span v-if="can('people.manage')"> <button class="secondary" @click="changeSkill(item,'已确认')">确认</button> <button class="secondary" @click="changeSkill(item,'已驳回')">驳回</button></span></div><p v-if="!skills.length" class="muted">暂无已解决且有验证记录的能力证据</p></section>
        <section class="panel"><h2>1 对 1 与成长行动</h2><div v-for="item in notes" :key="item.id" class="people-item"><b>{{ item.created_at }} · {{ item.confirmed_at ? '已确认' : '待本人确认' }}</b><p v-if="item.summary">要点：{{ item.summary }}</p><p v-if="item.actions">行动：{{ item.actions }}</p><p v-if="item.resource_request">资源诉求：{{ item.resource_request }}</p><p v-if="item.growth_goal">成长目标：{{ item.growth_goal }}</p><button v-if="selected.id===currentUser.id && !item.confirmed_at" class="secondary" @click="confirmNote(item.id)">确认纪要</button></div><h3>成长行动</h3><p v-for="item in actions" :key="item.id">{{ item.title }} · {{ item.status }} <button v-if="item.status==='进行中'" class="secondary" @click="changeAction(item,'已完成')">完成</button></p><form v-if="can('people.manage') && selected.id!==currentUser.id" class="form" @submit.prevent="addNote"><label>沟通要点<textarea v-model="noteForm.summary" /></label><label>行动约定<textarea v-model="noteForm.actions" /></label><label>资源诉求<textarea v-model="noteForm.resource_request" /></label><label>成长目标<textarea v-model="noteForm.growth_goal" /></label><button class="primary">记录待确认纪要</button></form></section></div>
      </template></template>
    <section v-else-if="active==='management'" class="panel"><h2>需要沟通的事</h2><div v-for="item in overview" :key="item.person.id" class="people-item"><h3>{{ item.person.name }}</h3><p v-for="cue in item.recommendations" :key="cue.rule+cue.issue_ids.join(',')">{{ cue.text }} <button v-for="id in cue.issue_ids" :key="id" class="people-link" @click="emit('openIssue',id)">#{{ id }}</button></p></div><p v-if="!overview.length" class="muted">暂无需要介入的异常</p></section>
    <section v-else-if="active==='notifications'" class="panel"><h2>我的提醒</h2><div v-for="item in notifications" :key="item.id" class="people-item"><b>{{ item.kind }} · {{ item.created_at }}</b><p>{{ item.content }}</p><button v-if="!item.read_at" class="secondary" @click="readNotice(item)">已读{{ item.issue_id ? '并打开问题' : '' }}</button></div><p v-if="!notifications.length" class="muted">暂无提醒</p></section>
    <section v-else-if="active==='report' && report" class="panel"><h2>{{ report.week_start }} 周报</h2><p class="muted">{{ report.source }} · {{ report.confirmed_at ? '已确认' : '待确认' }}</p><textarea v-model="report.content" class="people-report" /><div class="toolbar"><button class="secondary" @click="saveReport(false)">保存草稿</button><button v-if="can('reports.write')" class="primary" @click="saveReport(true)">确认周报</button></div></section>
  </div>
</template>
<style scoped>.panel{padding:16px}.people-error{color:#ad3131}.people-item{padding:12px 0;border-bottom:1px solid var(--line)}.people-item p{white-space:pre-wrap}.people-link{border:0;background:none;color:var(--blue);cursor:pointer}.people-report{width:100%;min-height:400px;box-sizing:border-box}</style>
