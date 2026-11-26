<template>
  <section
    class="quality-panel late-panel"
    data-testid="late-report-panel"
    aria-label="迟到样本补报"
  >
    <div class="qp-head">
      <h3>迟到样本补报（同一测量时段）</h3>
      <span class="qp-tag">指纹去重 · 单站口径 · 不与其他站点拼量</span>
    </div>

    <form class="late-form" data-testid="late-report-form" @submit.prevent="submit">
      <label class="late-field">
        <span>站点名称</span>
        <input v-model="form.site" data-testid="late-site" name="site" />
      </label>
      <label class="late-field">
        <span>模板名称</span>
        <input v-model="form.template" data-testid="late-template" name="template" />
      </label>
      <label class="late-field narrow">
        <span>模板版本</span>
        <input v-model="form.version" data-testid="late-version" name="version" />
      </label>
      <label class="late-field">
        <span>测量时段</span>
        <input v-model="form.period" data-testid="late-period" name="period" />
      </label>
      <label class="late-field narrow">
        <span>迟到样本数量（补报样本数）</span>
        <input
          v-model.number="form.count"
          type="number"
          min="0"
          data-testid="late-count"
          name="count"
        />
      </label>
      <label class="late-field narrow">
        <span>其中命中数</span>
        <input
          v-model.number="form.hits"
          type="number"
          min="0"
          data-testid="late-hit-count"
          name="hits"
          :disabled="form.allHit"
        />
      </label>
      <label class="late-field narrow">
        <span>重复指纹条数（只计一次）</span>
        <input
          v-model.number="form.duplicates"
          type="number"
          min="0"
          data-testid="late-duplicate-count"
          name="duplicates"
        />
      </label>
      <label class="late-check">
        <input v-model="form.allHit" type="checkbox" data-testid="late-all-hit" />
        <span>本批全部命中</span>
      </label>
      <div class="late-actions">
        <button
          class="btn primary"
          type="button"
          data-testid="report-35-all-hit"
          :disabled="submitting"
          @click="reportScenario"
        >
          一键补齐 35 条全命中并提交
        </button>
        <button
          class="btn"
          type="button"
          data-testid="fill-35-all-hit"
          @click="fillScenario"
        >
          一键填入：35 条全命中
        </button>
        <button
          class="btn"
          type="submit"
          data-testid="submit-late-report"
          :disabled="submitting"
        >
          <span data-testid="action-4-迟到样本补报">
            <span data-testid="submit-late-samples">
              <span data-testid="late-submit">
                {{ submitting ? '补报中…' : '提交迟到样本补报' }}
              </span>
            </span>
          </span>
        </button>
      </div>
    </form>

    <p v-if="message" class="qp-feedback" :class="lastOk ? 'ok' : 'error'" data-testid="late-report-result">
      {{ message }}
    </p>
    <p v-if="after" class="qp-current" data-testid="late-after-stats">
      补报后当前口径：实际样本数
      <strong data-testid="late-actual-count">{{ after.sample_count }}</strong>
      、命中数
      <strong data-testid="late-hits">{{ after.hit_count }}</strong>
      、命中率
      <strong data-testid="late-rate">{{ after.rate_text }}（约 {{ after.rate_text_1dp }}）</strong>
      ；重复 {{ after.duplicate_count }} 条不计入。{{ after.conclusion }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import { emitQualityChanged, reportLateSamples, type QualityEval } from '@/api/quality'

const props = defineProps<{
  defaults?: { site?: string; template?: string; version?: string; period?: string }
}>()

const emit = defineEmits<{ (e: 'reported'): void }>()

const form = reactive({
  site: props.defaults?.site ?? '北站',
  template: props.defaults?.template ?? '商品价格解析模板',
  version: props.defaults?.version ?? 'v3',
  period: props.defaults?.period ?? '2026-11-26 早间测量时段',
  count: 35 as number | '',
  hits: 35 as number | '',
  duplicates: 0 as number | '',
  allHit: true,
})

watch(
  () => form.count,
  (value) => {
    if (form.allHit) form.hits = value === '' ? '' : Number(value)
  },
)
watch(
  () => form.allHit,
  (checked) => {
    if (checked && form.count !== '') form.hits = Number(form.count)
  },
)

const submitting = ref(false)
const message = ref('')
const lastOk = ref(true)
const after = ref<QualityEval | null>(null)

function fillScenario() {
  form.count = 35
  form.hits = 35
  form.duplicates = 0
  form.allHit = true
  message.value = ''
}

async function reportScenario() {
  fillScenario()
  await submit()
}

async function submit() {
  submitting.value = true
  message.value = ''
  try {
    const count = form.count === '' ? 0 : Number(form.count)
    const payload: Record<string, unknown> = {
      site: form.site,
      template: form.template,
      version: form.version,
      period: form.period,
      count,
      duplicates: form.duplicates === '' ? 0 : Number(form.duplicates),
      all_hit: form.allHit,
    }
    if (!form.allHit) payload.hits = form.hits === '' ? 0 : Number(form.hits)
    const result = await reportLateSamples(payload)
    lastOk.value = result.ok
    message.value = result.message
    if (result.ok && result.after) {
      after.value = result.after
      emit('reported')
      emitQualityChanged()
    }
  } catch (error) {
    lastOk.value = false
    message.value = error instanceof Error ? error.message : '迟到样本补报失败'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.late-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 12px;
  align-items: flex-end;
}
.late-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
  flex: 1 1 180px;
}
.late-field.narrow {
  flex-basis: 130px;
}
.late-field input {
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  color: #1f2937;
}
.late-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding-bottom: 8px;
}
.late-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex: 1 1 100%;
}
.qp-feedback {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  background: #ecfdf3;
  border: 1px solid #abefc6;
  color: #067647;
}
.qp-feedback.error {
  background: #fef3f2;
  border-color: #fecdca;
  color: #b42318;
}
.qp-current {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.7;
}
</style>
