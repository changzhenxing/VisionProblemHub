<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ projectId: Number, api: Function, users: Array, permissions: Array })
const members = ref([]), milestones = ref([]), memberId = ref(''), memberRole = ref('成员'), title = ref(''), dueDate = ref(''), error = ref('')
const can = (key) => props.permissions?.includes(key)
async function load() { try { [members.value, milestones.value] = await Promise.all([props.api(`/api/projects/${props.projectId}/members`), props.api(`/api/projects/${props.projectId}/milestones`)]); error.value = '' } catch (cause) { error.value = cause.message } }
watch(() => props.projectId, load, { immediate: true })
async function addMember() { try { await props.api(`/api/projects/${props.projectId}/members/${memberId.value}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ member_role: memberRole.value }) }); memberId.value = ''; await load() } catch (cause) { error.value = cause.message } }
async function removeMember(id) { try { await props.api(`/api/projects/${props.projectId}/members/${id}`, { method: 'DELETE' }); await load() } catch (cause) { error.value = cause.message } }
async function addMilestone() { try { await props.api(`/api/projects/${props.projectId}/milestones`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.value, due_date: dueDate.value }) }); title.value = ''; dueDate.value = ''; await load() } catch (cause) { error.value = cause.message } }
async function toggleMilestone(item) { try { await props.api(`/api/milestones/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ completed: !item.completed_at }) }); await load() } catch (cause) { error.value = cause.message } }
</script>
<template>
  <div class="grid2"><section class="panel"><h3>项目成员</h3><p v-if="error" class="error">{{ error }}</p><p v-for="member in members" :key="member.user_id">{{ member.name }} · {{ member.member_role }} <button v-if="can('org.manage')" class="secondary" @click="removeMember(member.user_id)">移除</button></p><form v-if="can('org.manage')" class="toolbar" @submit.prevent="addMember"><select v-model="memberId" required><option value="">选择成员</option><option v-for="user in users" :key="user.id" :value="user.id">{{ user.name }}</option></select><select v-model="memberRole"><option v-for="role in ['成员','负责人','专家','协同']" :key="role">{{ role }}</option></select><button class="secondary">加入</button></form></section>
  <section class="panel"><h3>里程碑</h3><p v-for="item in milestones" :key="item.id"><button v-if="can('milestones.write')" class="secondary" @click="toggleMilestone(item)">{{ item.completed_at ? '✓' : '○' }}</button> {{ item.title }} · {{ item.due_date }}</p><p v-if="!milestones.length" class="muted">暂无里程碑</p><form v-if="can('milestones.write')" class="toolbar" @submit.prevent="addMilestone"><input v-model="title" placeholder="里程碑" required maxlength="160" /><input v-model="dueDate" type="date" required /><button class="secondary">添加</button></form></section></div>
</template>
<style scoped>.panel{padding:16px}.error{color:#ad3131}</style>
