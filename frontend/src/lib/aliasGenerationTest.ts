import { parseBooleanConfigValue } from '@/lib/configValueParsers'
import { apiFetch } from '@/lib/utils'

export interface AliasGenerationTestDraftSource extends Record<string, unknown> {
  id?: unknown
  type?: unknown
}

export interface AliasGenerationTestDraftConfig {
  cloudmail_alias_enabled?: unknown
  cloudmail_alias_emails?: unknown
  cloudmail_alias_mailbox_email?: unknown
  sources?: unknown
}

export interface AliasGenerationSourceOption {
  id: string
  type: string
}

export interface AliasGenerationModeSourceOptionsParams {
  useDraftConfig: boolean
  draftSourceOptions: AliasGenerationSourceOption[]
  savedSourceOptions: AliasGenerationSourceOption[]
}

export interface AliasGenerationModeSourceOptionsResult {
  configMode: 'draft' | 'saved'
  configLabel: string
  description: string
  emptyDescription: string
  sourceOptions: AliasGenerationSourceOption[]
}

export interface AliasGenerationTestRequest {
  sourceId: string
  useDraftConfig: boolean
  config?: AliasGenerationTestDraftConfig
}

export interface AliasGenerationTestResponse {
  ok: boolean
  sourceId: string
  sourceType: string
  aliasEmail: string
  realMailboxEmail: string
  serviceEmail: string
  captureSummary: Array<Record<string, unknown>>
  steps: string[]
  logs: string[]
  error: string
}

function isAliasGenerationDraftSource(
  value: unknown,
): value is AliasGenerationTestDraftSource {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function createAliasGenerationTestDraftConfig(
  formValues: Record<string, unknown>,
): AliasGenerationTestDraftConfig {
  return {
    cloudmail_alias_enabled: formValues.cloudmail_alias_enabled,
    cloudmail_alias_emails: formValues.cloudmail_alias_emails,
    cloudmail_alias_mailbox_email: formValues.cloudmail_alias_mailbox_email,
    sources: formValues.sources,
  }
}

function extractExplicitAliasGenerationSourceOptions(
  draftConfig: AliasGenerationTestDraftConfig,
): AliasGenerationSourceOption[] {
  if (!Array.isArray(draftConfig.sources)) {
    return []
  }

  return draftConfig.sources
    .map((value) => {
      if (!isAliasGenerationDraftSource(value)) {
        return null
      }

      const id = String(value.id || '').trim()
      if (!id) {
        return null
      }

      return {
        id,
        type: String(value.type || '').trim() || 'unknown',
      }
    })
    .filter((value): value is AliasGenerationSourceOption => value !== null)
}

export function deriveAliasGenerationSourceOptions(
  draftConfig: AliasGenerationTestDraftConfig,
): AliasGenerationSourceOption[] {
  if (!parseBooleanConfigValue(draftConfig.cloudmail_alias_enabled)) {
    return []
  }

  const explicitSourceOptions =
    extractExplicitAliasGenerationSourceOptions(draftConfig)
  if (explicitSourceOptions.length > 0) {
    return explicitSourceOptions
  }

  return [{ id: 'legacy-static', type: 'static_list' }]
}

export function resolveAliasGenerationModeSourceOptions({
  useDraftConfig,
  draftSourceOptions,
  savedSourceOptions,
}: AliasGenerationModeSourceOptionsParams): AliasGenerationModeSourceOptionsResult {
  if (useDraftConfig) {
    return {
      configMode: 'draft',
      configLabel: '当前未保存表单值',
      description: 'source 列表与测试请求都使用当前未保存表单值。',
      emptyDescription: '请先在当前表单中启用别名邮箱，并配置 sources 或旧版别名邮箱列表。',
      sourceOptions: draftSourceOptions,
    }
  }

  return {
    configMode: 'saved',
    configLabel: '已保存配置',
    description: 'source 列表与测试请求都使用已保存配置；未保存表单改动不会参与这次测试。',
    emptyDescription: '已保存配置中没有可测试的 alias source。请先保存配置，或切换为使用当前未保存表单值测试。',
    sourceOptions: savedSourceOptions,
  }
}

export async function runAliasGenerationTest(
  payload: AliasGenerationTestRequest,
): Promise<AliasGenerationTestResponse> {
  return apiFetch('/config/alias-test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
