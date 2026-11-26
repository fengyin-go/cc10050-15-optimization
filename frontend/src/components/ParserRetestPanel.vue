<template>
  <section v-if="loaded" class="quality-panel parser-panel" data-testid="parser-retest-panel">
    <div class="qp-head">
      <h3>复测接单台 · 领取审计发出的复测明细数据</h3>
      <button class="btn" type="button" data-testid="refresh-retest-desk" @click="reload">
        刷新接单状态
      </button>
    </div>

    <p class="muted small">
      接单时会核验复测单对应的<strong>站点</strong>与<strong>模板版本</strong>；
      核验通过后严格按该站点 + 模板版本 + 测量时段重放去重样本，
      复测命中明细会留存在审计页供确认升级建议。请优先使用下方模板列表中的
      「领取复测明细」行内动作（testid 遵循 action-模板ID-领取复测明细）。
    </p>

    <div v-for="order in orders" :key="order.code" class="order-card" data-testid="desk-order-card">
      <div class="order-head">
        <span>复测邀请：<strong data-testid="desk-order-code">{{ order.code }}</strong></span>
        <span class="status-pill" :data-status="order.status" data-testid="desk-order-status">
          {{ order.status === '待接单' ? '待接单（队列中）' : order.status }}
        </span>
      </div>

      <dl class="verify-grid">
        <div><dt>对应站点</dt><dd data-testid="desk-order-site">{{ order.站点名称 }}</dd></div>
        <div><dt>模板名称</dt><dd>{{ order.模板名称 }}</dd></div>
        <div><dt>对应模板版本</dt><dd data-testid="desk-order-version"><strong>{{ order.模板版本 }}</strong></dd></div>
        <div><dt>测量时段</dt><dd>{{ order.测量时段 }}</dd></div>
        <div><dt>发出时依据</dt><dd data-testid="desk-order-basis">
          {{ order.basis.sample_count }} 样本 / {{ order.basis.hit_count }} 命中 /
          {{ order.basis.rate_text }} / 阈值 {{ order.basis.threshold_text }} /
          规则 {{ order.basis.rule_version }}
        </dd></div>
        <div><dt>当前实际口径</dt><dd>
          {{ order.current?.sample_count }} 样本 / {{ order.current?.hit_count }} 命中 /
          {{ order.current?.rate_text }}（约 {{ order.current?.rate_text_1dp }}）
        </dd></div>
      </dl>

      <div class="desk-actions">
        <button
          class="btn primary"
          type="button"
          data-testid="verify-and-claim"
          :disabled="claiming || terminal(order.status)"
          @click="claim(scenarioTemplateId)"
        >
          接单核验并重放样本
        </button>
        <span v-if="feedback" class="desk-feedback" :class="feedbackOk ? 'ok-text' : 'bad-text'" data-testid="claim-feedback">
          {{ feedback }}
        </span>
      </div>

      <div v-if="order.claim" class="verify-ok" data-testid="claim-verified">
        ✅ {{ order.claim.verification_text }}
      </div>

      <div v-if="order.replay" class="replay-mini" data-testid="parser-replay-result">
        <h4>重放完成 · 命中明细已提交审计</h4>
        <p data-testid="parser-replay-summary">
          按 <strong data-testid="parser-replay-version">{{ order.replay.template_version }}</strong>
          版本实际重放 <strong>{{ order.replay.sample_count }}</strong> 个去重样本：
          命中 <strong>{{ order.replay.hit_count }}</strong>、
          未命中 <strong>{{ order.replay.miss_count }}</strong>、
          命中率 <strong>{{ order.replay.rate_text }}</strong>
          （约 {{ order.replay.rate_text_1dp }}）。
        </p>
        <div class="detail-scroll">
          <table class="mini-table" data-testid="parser-replay-details">
            <thead>
              <tr><th>样本指纹</th><th>站点</th><th>版本</th><th>重放结果</th><th>失败原因</th></tr>
            </thead>
            <tbody>
              <tr v-for="d in order.replay.details.slice(0, 40)" :key="d.record_id">
                <td>{{ d.fingerprint }}</td>
                <td>{{ d.site }}</td>
                <td>{{ d.template_version }}</td>
                <td :class="d.replay_hit ? 'ok-text' : 'bad-text'">{{ d.replay是否命中 }}</td>
                <td>{{ d.failure_reason || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted small" v-if="order.replay.details.length > 40">
          仅预览前 40 条，完整 {{ order.replay.details.length }} 条明细可在「解析质量审计」页查看。
        </p>
      </div>
    </div>

    <div class="template-hint" data-testid="desk-templates">
      <h4>同名模板的站点/版本（接单必须与邀请一致）</h4>
      <table class="mini-table">
        <thead><tr><th>模板ID</th><th>模板名称</th><th>适用站点</th><th>解析版本</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="t in templates" :key="String(t.id)" :data-testid="`desk-template-${t.id}`">
            <td>{{ t.id }}</td>
            <td>{{ t['模板名称'] }}</td>
            <td data-testid="desk-template-site">{{ t['适用站点'] }}</td>
            <td data-testid="desk-template-version">{{ t['解析版本'] }}</td>
            <td>{{ t.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <p v-else class="quality-loading" data-testid="parser-retest-loading">复测接单数据加载中…</p>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  claimRetest,
  emitQualityChanged,
  type QualityOrder,
} from '@/api/quality'

type DeskTemplate = {
  id: number
  模板名称: string
  适用站点: string
  解析版本: string
  status: string
}

const orders = ref<QualityOrder[]>([])
const templates = ref<DeskTemplate[]>([])
const scenarioTemplateId = ref(4)
const claiming = ref(false)
const feedback = ref('')
const feedbackOk = ref(true)
const loaded = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

function terminal(status: string): boolean {
  return status === '已结案' || status === '已取消'
}

const activeOrder = computed(() => orders.value[0] ?? null)

async function reload() {
  try {
    const response = await fetch('/api/quality/retest-desk')
    const data = await response.json()
    if (data?.ok) {
      orders.value = data.invitations ?? []
      templates.value = data.templates ?? []
      const north = (data.templates ?? []).find(
        (t: DeskTemplate) => t['适用站点'] === '北站' && t['解析版本'] === 'v3',
      )
      if (north) scenarioTemplateId.value = Number(north.id)
    }
  } catch {
    // 保留旧数据
  } finally {
    loaded.value = true
  }
}

async function claim(templateId: number) {
  if (!activeOrder.value) return
  claiming.value = true
  feedback.value = ''
  try {
    const result = await claimRetest(activeOrder.value.code, templateId)
    feedbackOk.value = result.ok
    feedback.value = result.message
    if (result.ok) {
      emitQualityChanged()
      await reload()
    }
  } catch (error) {
    feedbackOk.value = false
    feedback.value = error instanceof Error ? error.message : '接单重放失败'
  } finally {
    claiming.value = false
  }
}

function onChanged() {
  void reload()
}

onMounted(() => {
  void reload()
  timer = setInterval(() => void reload(), 2000)
  window.addEventListener('quality-changed', onChanged)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('quality-changed', onChanged)
})

defineExpose({ reload })
</script>

<style scoped>
.quality-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 12px 0 16px;
}
.qp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.qp-head h3 {
  margin: 0;
  font-size: 16px;
}
.muted {
  color: var(--muted);
}
.quality-loading {
  padding: 16px;
  color: var(--muted);
  font-size: 13px;
}
.small {
  font-size: 12px;
  line-height: 1.7;
}
.order-card {
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  padding: 12px;
  margin: 10px 0;
  background: #fcfcfd;
}
.order-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.status-pill {
  font-size: 12px;
  border-radius: 999px;
  padding: 3px 10px;
  background: #f2f4f7;
  border: 1px solid var(--border);
}
.verify-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 14px;
  margin: 0 0 10px;
}
.verify-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.verify-grid dd {
  margin: 2px 0 0;
  font-size: 13px;
  line-height: 1.5;
}
.desk-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.desk-feedback {
  font-size: 12px;
  line-height: 1.6;
  flex: 1;
}
.ok-text {
  color: #067647;
}
.bad-text {
  color: #b42318;
}
.verify-ok {
  margin-top: 10px;
  background: #ecfdf3;
  border: 1px solid #abefc6;
  color: #067647;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.7;
}
.replay-mini {
  margin-top: 10px;
}
.replay-mini h4 {
  margin: 0 0 6px;
  font-size: 14px;
}
.detail-scroll {
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.mini-table {
  width: 100%;
  border-collapse: collapse;
}
.mini-table th,
.mini-table td {
  border: 1px solid var(--border);
  padding: 5px 8px;
  font-size: 12px;
  text-align: left;
}
.template-hint {
  margin-top: 12px;
}
.template-hint h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
@media (max-width: 1100px) {
  .verify-grid {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }
}
</style>
