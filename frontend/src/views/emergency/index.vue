<template>
  <section class="page" data-module="emergency">
    <header class="page-head">
      <div>
        <h2>应急通信保障</h2>
        <p class="page-desc">
          报障按时间线登记：接到通知先落待响应，调派通信车与保障人员进入保障中，到场、撤离分段记录，
          撤离时间与结论不齐不许收口；同地点短时重复报障自动并单。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报障</button>
        <button class="btn" type="button" @click="openVehicles">通信车台账</button>
        <button class="btn" type="button" @click="exportRows">导出保障清单</button>
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
        <span>关键词</span>
        <input v-model="filters.keyword" placeholder="保障编号 / 地点 / 通信车编号" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>到场时长排序</span>
        <select v-model="filters.sort">
          <option value="">默认</option>
          <option value="duration_desc">到场时长由长到短</option>
          <option value="duration_asc">到场时长由短到长</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['保障编号'] }}</td>
          <td>
            {{ row['保障类型'] }}
            <span v-if="Number(row['合并报障数']) > 0" class="merge-badge">
              并入 {{ row['合并报障数'] }} 次重复报障
            </span>
          </td>
          <td>{{ row['保障地点'] }}</td>
          <td>{{ row['所属站点编号'] || '—' }}</td>
          <td>{{ row['通信车编号'] || '—' }}</td>
          <td>{{ row['保障人员'] || '—' }}</td>
          <td>{{ row['通知时间'] || '—' }}</td>
          <td>{{ row['调派时间'] || '—' }}</td>
          <td>{{ row['到达时间'] || '—' }}</td>
          <td>{{ row['撤离时间'] || '—' }}</td>
          <td>{{ row['到场时长'] || '—' }}</td>
          <td><span class="status-tag" :class="statusClass(row.status)">{{ row.status }}</span></td>
          <td class="row-actions">
            <template v-if="row.status === '待响应'">
              <button class="link" type="button" @click="openDispatch(row)">调派</button>
              <button class="link" type="button" @click="openBindSite(row)">绑定站点</button>
            </template>
            <template v-else-if="row.status === '保障中'">
              <button class="link" type="button" @click="openArrive(row)">
                {{ row['到达时间'] ? '补正到场' : '到场登记' }}
              </button>
              <button class="link danger" type="button" @click="openWithdraw(row)">撤离收口</button>
              <button class="link" type="button" @click="openBindSite(row)">绑定站点</button>
            </template>
            <button class="link" type="button" @click="openTimeline(row)">时间线</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保障记录，可先登记一条报障</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保障记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记报障 -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>登记报障（先落待响应）</h3>
        <div class="form-grid">
          <label>
            <span>保障类型 *</span>
            <input v-model="form.保障类型" placeholder="如：突发停电应急通信保障" />
          </label>
          <label>
            <span>保障地点 *</span>
            <input v-model="form.保障地点" placeholder="如：滨江会展中心" />
          </label>
          <label>
            <span>所属站点</span>
            <select v-model="form.所属站点编号">
              <option value="">未指定（撤离前需绑定或地点能匹配台账）</option>
              <option v-for="site in sites" :key="String(site.id)" :value="site['基站编号']">
                {{ site['基站编号'] }} {{ site['基站名称'] }}
              </option>
            </select>
          </label>
          <label>
            <span>通知时间</span>
            <input v-model="form.通知时间" type="datetime-local" />
          </label>
        </div>
        <p class="modal-tip">同地点 120 分钟内、且前一次保障尚未撤离的重复报障，会自动并入同一条时间线。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <!-- 调派 -->
    <div v-if="modal === 'dispatch'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>调派通信车与保障人员 — {{ activeRow?.['保障编号'] }}</h3>
        <div class="form-grid">
          <label>
            <span>所属站点</span>
            <select v-model="form.所属站点编号">
              <option value="">不修改</option>
              <option v-for="site in sites" :key="String(site.id)" :value="site['基站编号']">
                {{ site['基站编号'] }} {{ site['基站名称'] }}
              </option>
            </select>
          </label>
          <label>
            <span>通信车 *（实时可用性）</span>
            <select v-model="form.通信车编号">
              <option value="">请选择通信车</option>
              <option
                v-for="vehicle in vehicles"
                :key="vehicle['车辆编号']"
                :value="vehicle['车辆编号']"
                :disabled="!vehicle['可用']"
              >
                {{ vehicle['车辆编号'] }} {{ vehicle['车辆类型'] }} —
                {{ vehicle['可用'] ? '可用' : `不可用（${vehicle['占用原因']}）` }}
              </option>
            </select>
          </label>
          <label class="span-2">
            <span>保障人员 *</span>
            <input v-model="form.保障人员" placeholder="多人用顿号分隔，如：王磊、赵敏" />
          </label>
          <label>
            <span>调派时间</span>
            <input v-model="form.调派时间" type="datetime-local" />
          </label>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitAction('调派')">确认调派，进入保障中</button>
        </div>
      </div>
    </div>

    <!-- 到场登记 -->
    <div v-if="modal === 'arrive'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>到场登记 — {{ activeRow?.['保障编号'] }}</h3>
        <div class="form-grid">
          <label>
            <span>到达时间 *</span>
            <input v-model="form.到达时间" type="datetime-local" />
          </label>
        </div>
        <p class="modal-tip">到场时间与撤离时间分段记录；登记后保障仍处于保障中，撤离时再收口。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitAction('到场登记')">保存到场时间</button>
        </div>
      </div>
    </div>

    <!-- 撤离收口 -->
    <div v-if="modal === 'withdraw'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>撤离收口 — {{ activeRow?.['保障编号'] }}</h3>
        <div class="form-grid">
          <label>
            <span>撤离时间 *</span>
            <input v-model="form.撤离时间" type="datetime-local" />
          </label>
          <label>
            <span>结论写回站点</span>
            <input :value="writebackSiteLabel" disabled />
          </label>
          <label class="span-2">
            <span>保障结论 *</span>
            <textarea v-model="form.保障结论" rows="3" placeholder="如：传输链路恢复，基站运行正常，无次生告警"></textarea>
          </label>
        </div>
        <p v-if="!activeRow?.['到达时间']" class="modal-tip warn">到场时间尚未登记，需先完成到场登记才能收口。</p>
        <p v-else class="modal-tip">撤离时间与保障结论缺一不可；收口后结论写回站点台账，通信车随即释放。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitAction('撤离收口')">确认撤离并收口</button>
        </div>
      </div>
    </div>

    <!-- 绑定站点 -->
    <div v-if="modal === 'bind'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>绑定所属站点 — {{ activeRow?.['保障编号'] }}</h3>
        <div class="form-grid">
          <label class="span-2">
            <span>所属站点 *</span>
            <select v-model="form.所属站点编号">
              <option value="">请选择站点</option>
              <option v-for="site in sites" :key="String(site.id)" :value="site['基站编号']">
                {{ site['基站编号'] }} {{ site['基站名称'] }}
              </option>
            </select>
          </label>
        </div>
        <p class="modal-tip">撤离收口时按绑定站点把保障结论写回站点台账。</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitAction('绑定站点')">保存绑定</button>
        </div>
      </div>
    </div>

    <!-- 时间线 -->
    <div v-if="modal === 'timeline'" class="modal-mask" @click.self="closeModal">
      <div class="modal wide">
        <h3>保障时间线 — {{ activeRow?.['保障编号'] }}</h3>
        <ol class="timeline-list">
          <li v-for="(node, index) in timelineNodes" :key="index" class="timeline-item">
            <span class="timeline-time">{{ node['时间'] }}</span>
            <span class="timeline-node" :class="nodeClass(node['节点'])">{{ node['节点'] }}</span>
            <span class="timeline-desc">{{ node['说明'] }}</span>
          </li>
        </ol>
        <div v-if="mergedReports.length" class="merge-records">
          <h4>并入的重复报障</h4>
          <ul>
            <li v-for="(item, index) in mergedReports" :key="index">{{ item }}</li>
          </ul>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeModal">关闭</button>
        </div>
      </div>
    </div>

    <!-- 通信车台账 -->
    <div v-if="modal === 'vehicles'" class="modal-mask" @click.self="closeModal">
      <div class="modal wide">
        <h3>通信车台账与实时可用性</h3>
        <table class="data-table">
          <thead>
            <tr>
              <th>车辆编号</th><th>车辆类型</th><th>驻点</th><th>车辆状态</th><th>当前是否可用</th><th>占用原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="vehicle in vehicles" :key="vehicle['车辆编号']">
              <td>{{ vehicle['车辆编号'] }}</td>
              <td>{{ vehicle['车辆类型'] }}</td>
              <td>{{ vehicle['驻点'] }}</td>
              <td>{{ vehicle['车辆状态'] }}</td>
              <td>
                <span class="status-tag" :class="vehicle['可用'] ? 'ok' : 'busy'">
                  {{ vehicle['可用'] ? '可用' : '不可用' }}
                </span>
              </td>
              <td>{{ vehicle['占用原因'] || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeModal">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | TimelineNode[] | string[]>
interface TimelineNode { 时间: string; 节点: string; 说明: string }
interface VehicleRow {
  车辆编号: string
  车辆类型: string
  驻点: string
  车辆状态: string
  可用: boolean
  占用原因: string
}
interface SiteOption { id: number; 基站编号: string; 基站名称: string }

const ENDPOINT = '/api/emergency'
const columns = [
  { key: '保障编号', label: '保障编号' },
  { key: '保障类型', label: '保障类型' },
  { key: '保障地点', label: '保障地点' },
  { key: '所属站点编号', label: '所属站点' },
  { key: '通信车编号', label: '通信车' },
  { key: '保障人员', label: '保障人员' },
  { key: '通知时间', label: '通知时间' },
  { key: '调派时间', label: '调派时间' },
  { key: '到达时间', label: '到场时间' },
  { key: '撤离时间', label: '撤离时间' },
  { key: '到场时长', label: '到场时长' },
  { key: 'status', label: '状态' },
]
const statuses = ['待响应', '保障中', '已撤离']

const rows = ref<Row[]>([])
const total = ref(0)
const vehicles = ref<VehicleRow[]>([])
const sites = ref<SiteOption[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = reactive({ keyword: '', status: '', sort: '' })

const modal = ref<'' | 'create' | 'dispatch' | 'arrive' | 'withdraw' | 'bind' | 'timeline' | 'vehicles'>('')
const activeRow = ref<Row | null>(null)
const form = reactive<Record<string, string>>({})

const stats = computed(() => [
  { label: '待响应', value: rows.value.filter((row) => row.status === '待响应').length },
  { label: '保障中', value: rows.value.filter((row) => row.status === '保障中').length },
  { label: '已撤离', value: rows.value.filter((row) => row.status === '已撤离').length },
])

const writebackSiteLabel = computed(() => {
  const code = activeRow.value?.['所属站点编号']
  if (!code) return '未绑定站点：收口前需绑定或地点可匹配台账'
  const site = sites.value.find((item) => item['基站编号'] === code)
  return site ? `${site['基站编号']} ${site['基站名称']}` : String(code)
})

const mergedReports = computed<string[]>(() => {
  const value = activeRow.value?.['补充报障']
  return Array.isArray(value) ? (value as string[]) : []
})

const timelineNodes = computed<TimelineNode[]>(() => {
  const value = activeRow.value?.['timeline']
  return Array.isArray(value) ? (value as TimelineNode[]) : []
})

function nowLocalInput() {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.sort = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function closeModal() {
  modal.value = ''
  activeRow.value = null
  Object.keys(form).forEach((key) => delete form[key])
}

function openCreate() {
  errorMessage.value = ''
  form['保障类型'] = ''
  form['保障地点'] = ''
  form['所属站点编号'] = ''
  form['通知时间'] = nowLocalInput()
  modal.value = 'create'
}

function openDispatch(row: Row) {
  activeRow.value = row
  form['所属站点编号'] = String(row['所属站点编号'] || '')
  form['通信车编号'] = ''
  form['保障人员'] = ''
  form['调派时间'] = nowLocalInput()
  modal.value = 'dispatch'
}

function openArrive(row: Row) {
  activeRow.value = row
  form['到达时间'] = String(row['到达时间'] || '').replace(' ', 'T') || nowLocalInput()
  modal.value = 'arrive'
}

function openWithdraw(row: Row) {
  activeRow.value = row
  form['撤离时间'] = String(row['撤离时间'] || '').replace(' ', 'T') || nowLocalInput()
  form['保障结论'] = ''
  modal.value = 'withdraw'
}

function openBindSite(row: Row) {
  activeRow.value = row
  form['所属站点编号'] = String(row['所属站点编号'] || '')
  modal.value = 'bind'
}

function openTimeline(row: Row) {
  activeRow.value = row
  modal.value = 'timeline'
}

async function openVehicles() {
  errorMessage.value = ''
  await loadVehicles()
  modal.value = 'vehicles'
}

async function loadVehicles() {
  try {
    const response = await request(`${ENDPOINT}/vehicles`)
    if (!response.ok) throw new Error('通信车台账读取失败')
    const payload = await response.json()
    vehicles.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '通信车台账读取失败'
  }
}

async function loadSites() {
  try {
    const response = await request(`${ENDPOINT}/sites`)
    if (!response.ok) throw new Error('站点清单读取失败')
    const payload = await response.json()
    sites.value = payload.items ?? []
  } catch {
    // 站点下拉拉不到时仍允许手工走地点匹配，不阻断登记
    sites.value = []
  }
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...form } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '报障登记失败')
    noticeMessage.value = payload.message
    closeModal()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报障登记失败'
  }
}

async function submitAction(action: string) {
  if (!activeRow.value) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${activeRow.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...form } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '操作未生效')
    noticeMessage.value = payload.message
    closeModal()
    await Promise.all([reload(), loadVehicles()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作未生效'
  }
}

function statusClass(status: unknown) {
  if (status === '待响应') return 'pending'
  if (status === '保障中') return 'busy'
  return 'ok'
}

function nodeClass(node: string) {
  if (node === '补充报障') return 'pending'
  if (node === '撤离收口') return 'ok'
  if (node === '到场') return 'busy'
  return ''
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword.trim()) query.set('keyword', filters.keyword.trim())
  if (filters.status) query.set('status', filters.status)
  if (filters.sort) query.set('sort', filters.sort)
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('应急保障列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急保障列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadVehicles()
  void loadSites()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.notice-text {
  margin: 0 0 10px;
  padding: 8px 10px;
  border: 1px solid #b7e4c7;
  background: #f0fdf4;
  color: #166534;
  border-radius: 6px;
  font-size: 13px;
}
.merge-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 10px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.status-tag.pending { background: #fef3c7; color: #92400e; }
.status-tag.busy { background: #dbeafe; color: #1d4ed8; }
.status-tag.ok { background: #dcfce7; color: #166534; }
.link.danger { color: #b42318; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.25);
}
.modal.wide { width: 760px; }
.modal h3 { margin: 0 0 14px; font-size: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-grid label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.form-grid .span-2 { grid-column: span 2; }
.form-grid input,
.form-grid select,
.form-grid textarea {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  color: #1f2937;
}
.form-grid input:disabled { background: #f1f5f9; color: var(--muted); }
.modal-tip { margin: 12px 0 0; font-size: 12px; color: var(--muted); }
.modal-tip.warn { color: #b42318; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.timeline-list { list-style: none; margin: 0; padding: 0; }
.timeline-item {
  display: grid;
  grid-template-columns: 130px 84px 1fr;
  gap: 10px;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border);
  font-size: 13px;
}
.timeline-time { color: var(--muted); font-variant-numeric: tabular-nums; }
.timeline-node {
  text-align: center;
  border-radius: 10px;
  padding: 1px 0;
  font-size: 12px;
  background: #f1f5f9;
}
.timeline-node.busy { background: #dbeafe; color: #1d4ed8; }
.timeline-node.ok { background: #dcfce7; color: #166534; }
.timeline-node.pending { background: #fef3c7; color: #92400e; }
.merge-records { margin-top: 12px; font-size: 13px; }
.merge-records h4 { margin: 0 0 6px; font-size: 13px; }
.merge-records ul { margin: 0; padding-left: 18px; color: var(--muted); }
</style>
