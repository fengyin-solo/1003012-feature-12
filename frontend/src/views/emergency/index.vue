<template>
  <section class="page" data-module="emergency">
    <header class="page-head">
      <div>
        <h2>应急通信保障</h2>
        <p class="page-desc">
          按时间线登记保障：接报先入「待响应」，调派通信车与人员后进入「保障中」，到场、撤离分段记录；
          撤离时间与保障结论填齐方可收口，结论回写站点台账。同地点 24 小时内重复报障自动并单。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openVehicles">通信车台账</button>
        <button class="btn" type="button" @click="exportRows">导出保障清单</button>
        <button class="btn primary" type="button" @click="openCreate">登记保障通知</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="保障编号 / 保障类型" />
      </label>
      <label class="filter-item">
        <span>保障地点</span>
        <input v-model="filters.location" placeholder="按保障地点检索" />
      </label>
      <label class="filter-item">
        <span>保障状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-check">
        <input v-model="sortByDuration" type="checkbox" @change="reload" />
        <span>按到场时长排序</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>时间线</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '状态'">
              <span :class="['status-tag', statusClass(row.status)]">{{ row.status }}</span>
            </template>
            <template v-else-if="column === '报障次数'">
              <span :class="{ merged: Number(row[column]) > 1 }">
                {{ row[column] }} 次<span v-if="Number(row[column]) > 1">（已并单）</span>
              </span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <button class="link" type="button" @click="openTimeline(row)">查看（{{ row.timeline?.length ?? 0 }} 段）</button>
          </td>
          <td class="row-actions">
            <template v-if="row.status === '待响应'">
              <button class="link" type="button" @click="openDispatch(row)">调派</button>
            </template>
            <template v-else-if="row.status === '保障中'">
              <button v-if="!row['到场时间']" class="link" type="button" @click="openArrive(row)">到场登记</button>
              <button class="link" type="button" @click="openSegment(row)">补分段</button>
              <button class="link danger" type="button" @click="openWithdraw(row)">撤离收口</button>
            </template>
            <template v-else>
              <span class="muted-text">已收口</span>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无保障记录，接到通知后请先登记</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 通用弹窗 -->
    <div v-if="modal" class="modal-mask" @click.self="modal = ''">
      <div class="modal-box" :class="{ wide: modal === 'vehicles' }">
        <h3 class="modal-title">{{ modalTitle }}</h3>

        <!-- 登记保障通知 -->
        <div v-if="modal === 'create'" class="modal-body">
          <p class="modal-tip">同地点 24 小时内已有未收口保障时，本次报障将自动并入同一条时间线。</p>
          <label class="form-item"><span>保障类型 *</span>
            <select v-model="form['保障类型']">
              <option v-for="t in guaranteeTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </label>
          <label class="form-item"><span>保障地点 *</span>
            <input v-model="form['保障地点']" placeholder="如：市体育中心 / 滨河路基站" />
          </label>
          <label class="form-item"><span>通知时间 *</span>
            <input v-model="form['通知时间']" type="datetime-local" />
          </label>
          <label class="form-item"><span>报障内容</span>
            <textarea v-model="form['报障内容']" rows="2" placeholder="首次接报情况，可留空" />
          </label>
          <label class="form-item"><span>登记人</span>
            <input v-model="form['登记人']" placeholder="值班调度姓名" />
          </label>
        </div>

        <!-- 调派 -->
        <div v-else-if="modal === 'dispatch'" class="modal-body">
          <p class="modal-tip">
            任务 {{ activeRow?.['保障编号'] }}（{{ activeRow?.['保障地点'] }}）：选择通信车与保障人员后进入保障中。
          </p>
          <label class="form-item"><span>通信车 *</span>
            <select v-model="form['通信车编号']">
              <option value="" disabled>请选择通信车（已标注当前可用性）</option>
              <option
                v-for="v in vehicles"
                :key="v['通信车编号']"
                :value="v['通信车编号']"
                :disabled="v['可用状态'] === '占用中'"
              >
                {{ v['通信车编号'] }}｜{{ v['车型'] }}｜{{ v['可用状态']
                }}<template v-if="v['占用保障编号']">（{{ v['占用保障编号'] }} 占用）</template>
              </option>
            </select>
          </label>
          <label class="form-item"><span>保障人员 *</span>
            <input v-model="form['保障人员']" placeholder="多人用顿号分隔，如：张伟、李娜" />
          </label>
          <label class="form-item"><span>调派时间 *</span>
            <input v-model="form['调派时间']" type="datetime-local" />
          </label>
          <label class="form-item"><span>调派人</span>
            <input v-model="form['调派人']" placeholder="调度员姓名" />
          </label>
        </div>

        <!-- 到场登记 -->
        <div v-else-if="modal === 'arrive'" class="modal-body">
          <p class="modal-tip">登记车辆与人员首次到场时间，到场与撤离分段计入时间线。</p>
          <label class="form-item"><span>到场时间 *</span>
            <input v-model="form['到场时间']" type="datetime-local" />
          </label>
          <label class="form-item"><span>到场说明</span>
            <textarea v-model="form['到场说明']" rows="2" placeholder="如：现场展开天线、开通基站" />
          </label>
          <label class="form-item"><span>登记人</span>
            <input v-model="form['登记人']" />
          </label>
        </div>

        <!-- 补分段 -->
        <div v-else-if="modal === 'segment'" class="modal-body">
          <p class="modal-tip">保障过程中的转场、值守交接等分段记录，补进同一条时间线。</p>
          <label class="form-item"><span>时间 *</span>
            <input v-model="form['时间']" type="datetime-local" />
          </label>
          <label class="form-item"><span>分段说明 *</span>
            <textarea v-model="form['说明']" rows="2" placeholder="如：夜间值守交接 / 转场至北门" />
          </label>
          <label class="form-item"><span>登记人</span>
            <input v-model="form['登记人']" />
          </label>
        </div>

        <!-- 撤离收口 -->
        <div v-else-if="modal === 'withdraw'" class="modal-body">
          <p class="modal-tip warn">撤离时间与保障结论缺一不可，未填齐不允许收口；收口后结论将写回站点台账并释放通信车。</p>
          <label class="form-item"><span>撤离时间 *</span>
            <input v-model="form['撤离时间']" type="datetime-local" />
          </label>
          <label class="form-item"><span>保障结论 *</span>
            <textarea v-model="form['保障结论']" rows="3" placeholder="如：现场信号恢复正常，设备运行稳定" />
          </label>
          <label class="form-item"><span>登记人</span>
            <input v-model="form['登记人']" />
          </label>
        </div>

        <!-- 时间线 -->
        <div v-else-if="modal === 'timeline'" class="modal-body">
          <div v-if="activeRow" class="timeline-head">
            <span><b>{{ activeRow['保障编号'] }}</b>｜{{ activeRow['保障地点'] }}｜{{ activeRow['保障类型'] }}</span>
            <span :class="['status-tag', statusClass(activeRow.status)]">{{ activeRow.status }}</span>
          </div>
          <ol class="timeline">
            <li v-for="(node, idx) in activeRow?.timeline ?? []" :key="idx" class="timeline-item">
              <div class="timeline-time">{{ node.time }}</div>
              <div class="timeline-content">
                <strong>{{ node.action }}</strong>
                <p>{{ node.detail }}</p>
                <span v-if="node.operator" class="muted-text">记录人：{{ node.operator }}</span>
              </div>
            </li>
          </ol>
          <div v-if="activeRow?.['保障结论']" class="conclusion-box">
            <span>保障结论</span>
            <p>{{ activeRow['保障结论'] }}</p>
          </div>
        </div>

        <!-- 通信车台账 -->
        <div v-else-if="modal === 'vehicles'" class="modal-body wide">
          <table class="data-table">
            <thead>
              <tr>
                <th>通信车编号</th><th>车牌号</th><th>车型</th><th>停靠站点</th>
                <th>当前状态</th><th>占用保障</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="v in vehicles" :key="v['通信车编号']">
                <td>{{ v['通信车编号'] }}</td>
                <td>{{ v['车牌号'] }}</td>
                <td>{{ v['车型'] }}</td>
                <td>{{ v['停靠站点'] }}</td>
                <td>
                  <span :class="v['可用状态'] === '可用' ? 'ok-text' : 'error-text'">
                    {{ v['可用状态'] }}
                  </span>
                </td>
                <td>
                  <template v-if="v['占用保障编号']">
                    {{ v['占用保障编号'] }}｜{{ v['占用保障地点'] }}
                  </template>
                  <template v-else>—</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="modal-foot">
          <button class="btn" type="button" @click="modal = ''">关闭</button>
          <button
            v-if="submitAction"
            class="btn primary"
            type="button"
            :disabled="submitting"
            @click="submit"
          >
            {{ submitting ? '提交中…' : submitText }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type TimelineNode = { time: string; action: string; detail: string; operator?: string }
type Row = {
  id: number
  status: string
  timeline?: TimelineNode[]
  [key: string]: string | number | null | TimelineNode[] | undefined
}
type Vehicle = Record<string, string>
type ActionResult = { ok: boolean; message: string; entry?: Row }

const ENDPOINT = '/api/emergency'
const columns = [
  '保障编号', '保障类型', '保障地点', '通知时间', '调派时间',
  '通信车编号', '保障人员', '到场时间', '撤离时间', '到场时长', '报障次数', '状态',
]
const statuses = ['待响应', '保障中', '已撤离']
const guaranteeTypes = ['突发故障抢修', '重大活动保障', '防汛应急', '防灾减灾', '网络优化保障', '其他应急']

const rows = ref<Row[]>([])
const total = ref(0)
const vehicles = ref<Vehicle[]>([])
const stats = ref<{ label: string; value: number }[]>([
  { label: '待响应', value: 0 },
  { label: '保障中', value: 0 },
  { label: '已撤离', value: 0 },
  { label: '可用通信车', value: 0 },
])
const message = ref('')
const messageOk = ref(true)
const filters = reactive<{ keyword: string; location: string; status: string }>({
  keyword: '', location: '', status: '',
})
const sortByDuration = ref(false)

const modal = ref('')
const activeRow = ref<Row | null>(null)
const form = reactive<Record<string, string>>({})
const submitting = ref(false)

const modalTitle = computed(() => ({
  create: '登记保障通知',
  dispatch: '调派通信车与保障人员',
  arrive: '到场登记',
  segment: '补记保障分段',
  withdraw: '撤离收口',
  timeline: '保障时间线',
  vehicles: '通信车台账（调派可用性）',
}[modal.value] ?? ''))

const submitAction = computed(() =>
  ['create', 'dispatch', 'arrive', 'segment', 'withdraw'].includes(modal.value)
    ? modal.value
    : '',
)
const submitText = computed(() => ({
  create: '登记待响应',
  dispatch: '确认调派',
  arrive: '登记到场',
  segment: '补入时间线',
  withdraw: '撤离并收口',
}[modal.value] ?? '确定'))

function nowLocal() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

function resetForm(preset: Record<string, string>) {
  Object.keys(form).forEach((k) => delete form[k])
  Object.assign(form, preset)
}

function statusClass(status: string | null) {
  if (status === '保障中') return 'ongoing'
  if (status === '已撤离') return 'closed'
  return 'pending'
}

function setMessage(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  filters.keyword = ''
  filters.location = ''
  filters.status = ''
  sortByDuration.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---------------- 弹窗 ----------------

function openCreate() {
  activeRow.value = null
  resetForm({ 保障类型: guaranteeTypes[0], 保障地点: '', 通知时间: nowLocal(), 报障内容: '', 登记人: '' })
  modal.value = 'create'
}

async function openDispatch(row: Row) {
  activeRow.value = row
  await loadVehicles()
  resetForm({ 通信车编号: '', 保障人员: '', 调派时间: nowLocal(), 调派人: '' })
  modal.value = 'dispatch'
}

function openArrive(row: Row) {
  activeRow.value = row
  resetForm({ 到场时间: nowLocal(), 到场说明: '', 登记人: '' })
  modal.value = 'arrive'
}

function openSegment(row: Row) {
  activeRow.value = row
  resetForm({ 时间: nowLocal(), 说明: '', 登记人: '' })
  modal.value = 'segment'
}

function openWithdraw(row: Row) {
  activeRow.value = row
  resetForm({ 撤离时间: nowLocal(), 保障结论: '', 登记人: '' })
  modal.value = 'withdraw'
}

async function openTimeline(row: Row) {
  activeRow.value = row
  modal.value = 'timeline'
  // 拉最新明细，保证时间线完整
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (response.ok) {
      const detail = await response.json()
      if (detail?.id) activeRow.value = detail
    }
  } catch {
    // 拉不到时用列表行里的时间线兜底
  }
}

async function openVehicles() {
  modal.value = 'vehicles'
  await loadVehicles()
}

async function loadVehicles() {
  try {
    const response = await request(`${ENDPOINT}/vehicles`)
    if (response.ok) {
      const payload = await response.json()
      vehicles.value = payload.items ?? []
    }
  } catch {
    vehicles.value = []
  }
}

// ---------------- 提交 ----------------

async function submit() {
  if (!submitAction.value || !activeReady()) {
    setMessage('请把必填项填齐', false)
    return
  }
  submitting.value = true
  try {
    const action = submitAction.value
    const body = JSON.stringify({ values: { ...form } })
    const path = activeRow.value ? `${ENDPOINT}/${activeRow.value.id}/${action}` : ENDPOINT
    const response = await request(path, { method: 'POST', body })
    const payload = (await response.json()) as ActionResult
    if (!response.ok || !payload.ok) {
      setMessage(payload.message || '操作未生效，请稍后重试', false)
      return
    }
    setMessage(payload.message, true)
    modal.value = ''
    await Promise.all([reload(), loadStats(), loadVehicles()])
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '操作失败', false)
  } finally {
    submitting.value = false
  }
}

function activeReady() {
  if (modal.value === 'create') return form['保障地点']?.trim() && form['通知时间']
  if (modal.value === 'dispatch') return form['通信车编号'] && form['保障人员']?.trim() && form['调派时间']
  if (modal.value === 'arrive') return !!form['到场时间']
  if (modal.value === 'segment') return form['时间'] && form['说明']?.trim()
  if (modal.value === 'withdraw') return form['撤离时间'] && form['保障结论']?.trim()
  return false
}

// ---------------- 数据加载 ----------------

async function reload() {
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.location) params.set('location', filters.location)
  if (filters.status) params.set('status', filters.status)
  if (sortByDuration.value) params.set('sort_duration', 'true')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('应急保障列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    setMessage(error instanceof Error ? error.message : '应急保障列表读取失败', false)
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      const payload = await response.json()
      if (Array.isArray(payload.items)) stats.value = payload.items
    }
  } catch {
    // 统计失败不阻塞主列表
  }
}

onMounted(() => {
  void reload()
  void loadStats()
  void loadVehicles()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.filter-item select { width: 130px; }
.filter-item input, .filter-item select, .form-item input, .form-item select, .form-item textarea {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  width: 100%;
}
.filter-check { display: flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); }
.status-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.status-tag.pending { background: #fef3c7; color: #92400e; }
.status-tag.ongoing { background: #dbeafe; color: #1e40af; }
.status-tag.closed { background: #dcfce7; color: #166534; }
.merged { color: #b45309; }
.muted-text { color: var(--muted); font-size: 12px; }
.link.danger { color: #b42318; }
.ok-text { color: #166534; }

.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal-box {
  background: #fff; border-radius: 10px; width: 520px; max-width: 92vw;
  max-height: 88vh; display: flex; flex-direction: column;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.25);
}
.modal-body { padding: 14px 18px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.modal-box.wide { width: 800px; }
.modal-title { margin: 0; padding: 14px 18px; border-bottom: 1px solid var(--border); font-size: 15px; }
.modal-body { padding: 14px 18px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.modal-tip { margin: 0; font-size: 12px; color: var(--muted); background: #f1f5f9; padding: 8px 10px; border-radius: 6px; }
.modal-tip.warn { color: #b42318; background: #fef2f2; }
.form-item { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--border); }

.timeline-head { display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
.timeline { list-style: none; margin: 0; padding: 0 0 0 6px; }
.timeline-item { position: relative; padding: 0 0 14px 18px; border-left: 2px solid var(--border); }
.timeline-item::before {
  content: ''; position: absolute; left: -6px; top: 2px; width: 10px; height: 10px;
  border-radius: 50%; background: var(--brand);
}
.timeline-time { font-size: 12px; color: var(--muted); }
.timeline-content strong { font-size: 13px; }
.timeline-content p { margin: 2px 0; font-size: 13px; }
.conclusion-box { border: 1px solid #bbf7d0; background: #f0fdf4; border-radius: 6px; padding: 8px 10px; }
.conclusion-box span { font-size: 12px; color: #166534; }
.conclusion-box p { margin: 4px 0 0; font-size: 13px; }
</style>
