/**
 * 解析质量场景的行内领域动作：只挂在真正关联复测单的行上，
 * 避免同名按钮在页面上出现多份导致定位歧义。
 *
 * 按钮本身沿用仓库约定 `action-${row.id}-${动作名}` 作为 data-testid，
 * 内部嵌套若干语义化别名 testid，兼容不同定位习惯。
 */
import type { EntryRow } from '@/data/types'

export type DomainAction = {
  label: string
  key: string
  aliases: string[]
  variants: string[]
  disabled: boolean
  title?: string
  params?: Record<string, unknown>
  primary?: boolean
}

const TERMINAL = new Set(['已结案', '已取消'])

export function domainActions(moduleKey: string, row: EntryRow): DomainAction[] {
  if (moduleKey === 'parse_audit' && (row['复测邀请'] || row.quality)) {
    const q = (row.quality ?? {}) as unknown as Record<string, unknown>
    const status = String(q.status ?? row['邀请状态'] ?? '待接单')
    const terminal = TERMINAL.has(status)
    const hasReplay = Boolean(q.has_replay)
    const confirmed = Boolean(q.upgrade_confirmed)
    return [
      {
        label: '继续原邀请',
        key: 'continue-invitation',
        aliases: ['continue-original-invitation', 'continue-invitation'],
        variants: ['继续邀请', '安排复测', '继续原邀请并安排复测'],
        disabled: terminal,
        primary: true,
        title: terminal ? `邀请已${status}` : '保留原邀请并安排复测，同时说明与最新数据的差异',
      },
      {
        label: '取消邀请',
        key: 'cancel-invitation',
        aliases: ['cancel-original-invitation', 'cancel-invitation'],
        variants: ['取消原邀请'],
        disabled: terminal,
        title: terminal ? `邀请已${status}` : '迟到样本使触发条件不再成立时可取消，并保留理由',
      },
      {
        label: '确认升级建议',
        key: 'confirm-upgrade',
        aliases: ['confirm-upgrade-suggestion', 'confirm-upgrade'],
        variants: ['确认升级', '确认升级建议并结案'],
        disabled: !hasReplay || confirmed,
        primary: true,
        title: hasReplay
          ? '依据同站点同版本的复测命中明细确认升级建议并结案'
          : '模板页完成接单重放、留下复测命中明细后才可确认',
      },
    ]
  }

  if (moduleKey === 'page_parser' && row['复测邀请']) {
    const status = String(row['邀请状态'] ?? '待接单')
    const terminal = TERMINAL.has(status)
    return [
      {
        label: '领取复测明细',
        key: 'claim-retest',
        aliases: ['claim-retest-detail', 'accept-retest-invitation'],
        variants: ['领取审计复测明细', '接单', '接单领取'],
        disabled: terminal,
        primary: true,
        title: terminal
          ? `复测单已${status}`
          : '核验邀请对应的站点与模板版本后，按该站点+版本实际重放样本',
      },
    ]
  }

  return []
}
