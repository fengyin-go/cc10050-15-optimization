/** 解析质量一致性相关接口：依据看板、迟到补报、复测邀请状态机。 */
import { request } from './client'

export type QualityEval = {
  site: string
  template: string
  version: string
  period: string
  sample_count: number
  hit_count: number
  miss_count: number
  reported_count: number
  duplicate_count: number
  rate: number
  rate_text: string
  rate_text_1dp: string
  min_samples: number
  meets_min_samples: boolean
  threshold: number
  threshold_text: string
  below_threshold: boolean
  degraded: boolean
  rule_version: string
  rule_version_text: string
  trigger_condition: string
  conclusion: string
}

export type ReplayDetail = {
  record_id: number
  fingerprint: string
  site: string
  template_version: string
  source: string
  original_hit: boolean
  replay_hit: boolean
  replay是否命中: string
  original是否命中: string
  consistent: boolean
  failure_reason: string
}

export type QualityOrder = {
  id: number
  code: string
  audit_id: number
  站点名称: string
  模板名称: string
  模板版本: string
  测量时段: string
  status: string
  in_queue: boolean
  basis: {
    sample_count: number
    hit_count: number
    miss_count: number
    rate_text: string
    min_samples: number
    threshold_text: string
    rule_version: string
    trigger_condition: string
  }
  decision: string
  decision_reason: string
  claim: { verification_text: string } | null
  replay: {
    sample_count: number
    hit_count: number
    miss_count: number
    rate_text: string
    rate_text_1dp: string
    template_version: string
    reason_distribution: string
    details: ReplayDetail[]
  } | null
  upgrade: {
    suggested: boolean
    confirmed: boolean
    suggestion: string
    note: string
  }
  timeline: { at: string; event: string; note: string }[]
  current?: QualityEval
  can_retest: boolean
}

export type QualityBoard = {
  ok: boolean
  rule: {
    version: string
    min_samples: number
    threshold: number
    threshold_text: string
    trigger_condition: string
  }
  scenario: {
    site: string
    template: string
    version: string
    period: string
    audit_id: number
    template_id: number
  }
  evaluation: QualityEval
  scopes: QualityEval[]
  hit_records?: {
    id: number
    站点名称: string
    模板版本: string
    样本指纹: string
    是否命中: string
    来源: string
    失败原因: string
  }[]
  invitation: QualityOrder | null
  invitations: QualityOrder[]
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return (await response.json()) as T
}

export async function fetchBoard(): Promise<QualityBoard> {
  const response = await request('/api/quality/board')
  if (!response.ok) throw new Error('质量依据看板读取失败')
  return (await response.json()) as Promise<QualityBoard>
}

export async function reportLateSamples(
  body: Record<string, unknown>,
): Promise<{ ok: boolean; message: string; after?: QualityEval }> {
  return postJson('/api/quality/late-samples', body)
}

export async function continueInvitation(code: string): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/quality/orders/${encodeURIComponent(code)}/continue`, {})
}

export async function cancelInvitation(code: string): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/quality/orders/${encodeURIComponent(code)}/cancel`, {})
}

export async function claimRetest(
  code: string,
  templateId: number,
): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/quality/orders/${encodeURIComponent(code)}/claim`, {
    template_id: templateId,
  })
}

export async function confirmUpgrade(
  code: string,
  version?: string,
): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/quality/orders/${encodeURIComponent(code)}/confirm`, { version })
}

/** 通知同页/跨组件的质量数据需要刷新（跨标签页由轮询兜底）。 */
export function emitQualityChanged(): void {
  window.dispatchEvent(new CustomEvent('quality-changed'))
}
