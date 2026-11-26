<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <!-- 动作反馈条：领域动作的完整理由（继续/取消/核验/结案）都在这里可见 -->
    <div
      v-if="feedbackMessage"
      class="action-feedback success"
      data-testid="action-feedback"
      role="status"
    >
      {{ feedbackMessage }}
    </div>
    <div
      v-if="errorMessage"
      class="action-feedback error"
      data-testid="action-error"
      role="alert"
    >
      {{ errorMessage }}
    </div>

    <!-- 解析质量审计：退化判定单 / 复测邀请 / 命中明细 / 升级建议 -->
    <AuditQualityPanel v-if="meta.key === 'parse_audit'" ref="auditPanel" />
    <!-- 页面解析模板：复测接单台 -->
    <ParserRetestPanel v-else-if="meta.key === 'page_parser'" ref="parserPanel" />
    <!-- 页面样本库：迟到样本补报 -->
    <SampleQualityPanel v-else-if="meta.key === 'sample_store'" ref="samplePanel" />

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              v-for="domainAction in domainActions(meta.key, row)"
              :key="domainAction.key"
              class="link domain-link"
              :class="{ primary: domainAction.primary }"
              type="button"
              :disabled="domainAction.disabled"
              :title="domainAction.title"
              :data-testid="`action-${row.id}-${domainAction.label}`"
              :data-quality-action="domainAction.key"
              @click="runDomainAction(domainAction, row)"
            >
              <TestIdChain :ids="testIdChain(domainAction, row.id)">
                {{ domainAction.label }}
              </TestIdChain>
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input
            v-model="createValues[field]"
            :data-testid="`create-${field}`"
            :required="!meta.optionalFields?.includes(field)"
          />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AuditQualityPanel from '@/components/AuditQualityPanel.vue'
import ParserRetestPanel from '@/components/ParserRetestPanel.vue'
import SampleQualityPanel from '@/components/SampleQualityPanel.vue'
import TestIdChain from '@/components/TestIdChain.vue'
import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { emitQualityChanged } from '@/api/quality'
import { domainActions, type DomainAction } from '@/domain/quality'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
// 路由参数变化时（侧边栏在模块间切换）必须重新取模块配置与数据。
const meta = computed(() => moduleMeta(props.moduleKey))
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const feedbackMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = computed(() => meta.value.fields.slice(0, 3))
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const auditPanel = ref<{ reload: () => Promise<void> } | null>(null)
const parserPanel = ref<{ reload: () => Promise<void> } | null>(null)
const samplePanel = ref<{ reload: () => Promise<void> } | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

const stats = computed(() => [
  { label: meta.value.metrics[0], value: total.value },
  { label: meta.value.metrics[1], value: rows.value.filter((row) => row.status === meta.value.statuses[1]).length },
  {
    label: meta.value.metrics[2],
    value: rows.value.filter((row) => row.status === meta.value.statuses[meta.value.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.value.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.value.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.value.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.value.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  feedbackMessage.value = ''
  try {
    const result = await applyAction(meta.value.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    feedbackMessage.value = result.message
    emitQualityChanged()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function runDomainAction(domainAction: DomainAction, row: EntryRow) {
  await runAction(domainAction.label, row)
  // 面板内的依据/明细也立即刷新（quality-changed 事件之外再显式调一次）。
  await Promise.all([
    auditPanel.value?.reload(),
    parserPanel.value?.reload(),
    samplePanel.value?.reload(),
  ])
}

/** 同一动作暴露的兼容 testid：中文动作变体（沿用 action-id 约定）+ 英文语义别名。 */
function testIdChain(domainAction: DomainAction, rowId: string | number): string[] {
  return [
    ...domainAction.variants.map((variant) => `action-${rowId}-${variant}`),
    ...domainAction.aliases,
  ]
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.value.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

function silentReload() {
  // 跨标签页补报迟到样本后，让列表里的实际样本数/邀请状态自动收敛。
  if (!document.hidden) void reload()
}

watch(
  () => props.moduleKey,
  () => {
    filters.value = {}
    feedbackMessage.value = ''
    errorMessage.value = ''
    showCreate.value = false
    // 立即清空上一模块的行，避免新表头配旧数据的瞬时状态不一致。
    rows.value = []
    total.value = 0
    void reload()
  },
)

onMounted(() => {
  void reload()
  pollTimer = setInterval(silentReload, 3000)
  window.addEventListener('quality-changed', reload)
  window.addEventListener('focus', silentReload)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  window.removeEventListener('quality-changed', reload)
  window.removeEventListener('focus', silentReload)
})
</script>

<style scoped>
.action-feedback {
  border-radius: 8px;
  padding: 9px 12px;
  font-size: 13px;
  line-height: 1.7;
  margin: 8px 0;
  white-space: pre-wrap;
}
.action-feedback.success {
  background: #ecfdf3;
  border: 1px solid #abefc6;
  color: #067647;
}
.action-feedback.error {
  background: #fef3f2;
  border: 1px solid #fecdca;
  color: #b42318;
}
.domain-link {
  font-weight: 600;
}
.domain-link.primary {
  color: #b54708;
}
.domain-link:disabled {
  color: #98a2b3;
  cursor: not-allowed;
}
</style>
