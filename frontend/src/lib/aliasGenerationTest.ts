import { parseBooleanConfigValue } from '@/lib/configValueParsers'
import { apiFetch } from '@/lib/utils'

export type AliasGenerationSourceType =
  | 'static_list'
  | 'simple_generator'
  | 'vend_email'

export interface AliasGenerationTestDraftSource extends Record<string, unknown> {
  id?: unknown
  type?: unknown
  emails?: unknown
  prefix?: unknown
  suffix?: unknown
  count?: unknown
  middle_length_min?: unknown
  middle_length_max?: unknown
  register_url?: unknown
  cloudmail_api_base?: unknown
  cloudmail_admin_email?: unknown
  cloudmail_admin_password?: unknown
  cloudmail_domain?: unknown
  cloudmail_subdomain?: unknown
  cloudmail_timeout?: unknown
  alias_domain?: unknown
  alias_domain_id?: unknown
  alias_count?: unknown
  state_key?: unknown
}

export interface AliasGenerationTestDraftConfig {
  cloudmail_alias_enabled?: unknown
  cloudmail_alias_emails?: unknown
  cloudmail_alias_service_static_enabled?: unknown
  cloudmail_alias_service_simple_enabled?: unknown
  cloudmail_alias_service_simple_prefix?: unknown
  cloudmail_alias_service_simple_suffix?: unknown
  cloudmail_alias_service_simple_count?: unknown
  cloudmail_alias_service_simple_middle_length_min?: unknown
  cloudmail_alias_service_simple_middle_length_max?: unknown
  cloudmail_alias_service_vend_enabled?: unknown
  cloudmail_alias_service_vend_source_id?: unknown
  cloudmail_alias_service_vend_alias_count?: unknown
  cloudmail_alias_service_vend_state_key?: unknown
  cloudmail_alias_vend_enabled?: unknown
  cloudmail_alias_vend_alias_count?: unknown
  cloudmail_alias_vend_source_id?: unknown
  cloudmail_alias_vend_state_key?: unknown
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

export interface AliasGenerationTestAccount extends Record<string, unknown> {
  realMailboxEmail?: unknown
  real_mailbox_email?: unknown
  serviceEmail?: unknown
  service_email?: unknown
  password?: unknown
  servicePassword?: unknown
  service_password?: unknown
  username?: unknown
  userName?: unknown
}

export interface AliasGenerationTestAccountIdentity extends Record<string, unknown> {
  serviceAccountEmail?: unknown
  service_account_email?: unknown
  confirmationInboxEmail?: unknown
  confirmation_inbox_email?: unknown
  realMailboxEmail?: unknown
  real_mailbox_email?: unknown
  servicePassword?: unknown
  service_password?: unknown
  username?: unknown
}

export interface AliasGenerationTestAlias extends Record<string, unknown> {
  email?: unknown
  aliasEmail?: unknown
}

export interface AliasGenerationTestStage extends Record<string, unknown> {
  code?: unknown
  label?: unknown
  status?: unknown
  detail?: unknown
}

export interface AliasGenerationTestCurrentStage extends Record<string, unknown> {
  code?: unknown
  label?: unknown
}

export interface AliasGenerationTestFailure extends Record<string, unknown> {
  stageCode?: unknown
  stageLabel?: unknown
  reason?: unknown
  retryable?: unknown
}

export interface AliasGenerationTestResponse {
  ok: boolean
  sourceId: string
  sourceType: string
  aliasEmail: string
  realMailboxEmail: string
  serviceEmail: string
  accountIdentity?: AliasGenerationTestAccountIdentity
  account?: AliasGenerationTestAccount
  aliases?: AliasGenerationTestAlias[]
  currentStage?: AliasGenerationTestCurrentStage
  stages?: AliasGenerationTestStage[]
  failure?: AliasGenerationTestFailure
  captureSummary: Array<Record<string, unknown>>
  steps: string[]
  logs: string[]
  error: string
}

export interface AliasGenerationTestDisplayStage {
  key: string
  code: string
  label: string
  status: string
  detail: string
  isCurrent: boolean
}

export interface AliasGenerationTestDisplay {
  ok: boolean
  sourceId: string
  sourceType: string
  summaryAliasEmail: string
  account: {
    realMailboxEmail: string
    serviceEmail: string
    password: string
    username: string
  }
  aliases: Array<{
    key: string
    email: string
  }>
  currentStage: {
    code: string
    label: string
  }
  stages: AliasGenerationTestDisplayStage[]
  failure: {
    stageCode: string
    stageLabel: string
    reason: string
    retryable?: boolean
  }
  captureSummary: Array<Record<string, unknown>>
  logs: string[]
  error: string
}

const ALIAS_TEST_STAGE_LABELS: Record<string, string> = {
  register_submit: '注册表单提交',
  fetch_confirmation_mail: '查找确认邮件',
  open_confirmation_link: '打开确认链接',
  list_aliases: '列出现有别名',
  create_aliases: '创建别名',
  aliases_ready: '别名预览已生成',
  session_ready: '会话已就绪',
  save_state: '保存预览状态',
  load_source: '加载来源',
  acquire_alias: '生成别名',
}

function normalizeAliasGenerationStageLabel(code: string, label: string): string {
  return label || ALIAS_TEST_STAGE_LABELS[code] || code
}

function normalizeAliasGenerationCurrentStage(
  value: unknown,
): { code: string; label: string } {
  const stage = asRecord(value)
  const code = stringifyFieldValue(stage?.code)
  const label = normalizeAliasGenerationStageLabel(
    code,
    stringifyFieldValue(stage?.label),
  )

  return {
    code,
    label,
  }
}

function normalizeAliasGenerationAliases(
  response: AliasGenerationTestResponse,
): Array<{ key: string; email: string }> {
  const aliases = Array.isArray(response.aliases)
    ? response.aliases
        .map((item, index) => {
          const alias = asRecord(item)
          const email = stringifyFieldValue(alias?.email ?? alias?.aliasEmail)
          if (!email) {
            return null
          }

          return {
            key: `${email}-${index + 1}`,
            email,
          }
        })
        .filter((item): item is { key: string; email: string } => item !== null)
    : []

  if (aliases.length > 0) {
    return aliases
  }

  const fallbackAliasEmail = stringifyFieldValue(response.aliasEmail)
  if (!fallbackAliasEmail) {
    return []
  }

  return [{ key: `${fallbackAliasEmail}-1`, email: fallbackAliasEmail }]
}

function normalizeAliasGenerationAccount(
  response: AliasGenerationTestResponse,
): AliasGenerationTestDisplay['account'] {
  const accountIdentity = asRecord(response.accountIdentity)
  const account = asRecord(response.account)

  return {
    realMailboxEmail:
      stringifyFieldValue(
        accountIdentity?.realMailboxEmail
        ?? accountIdentity?.real_mailbox_email
        ?? account?.realMailboxEmail
        ?? account?.real_mailbox_email,
      )
      || stringifyFieldValue(response.realMailboxEmail),
    serviceEmail:
      stringifyFieldValue(
        accountIdentity?.serviceAccountEmail
        ?? accountIdentity?.service_account_email
        ?? account?.serviceEmail
        ?? account?.service_email,
      )
      || stringifyFieldValue(response.serviceEmail),
    password:
      stringifyFieldValue(
        accountIdentity?.servicePassword
        ?? accountIdentity?.service_password
        ?? account?.password
        ?? account?.servicePassword
        ?? account?.service_password,
      ),
    username: stringifyFieldValue(
      accountIdentity?.username ?? account?.username ?? account?.userName,
    ),
  }
}

function normalizeAliasGenerationStages(
  response: AliasGenerationTestResponse,
  currentStageCode: string,
): AliasGenerationTestDisplayStage[] {
  if (Array.isArray(response.stages) && response.stages.length > 0) {
    return response.stages
      .map((item, index) => {
        const stage = asRecord(item)
        if (!stage) {
          return null
        }

        const code = stringifyFieldValue(stage.code)
        const label = normalizeAliasGenerationStageLabel(
          code,
          stringifyFieldValue(stage.label),
        )
        const status = stringifyFieldValue(stage.status)
        const detail = stringifyFieldValue(stage.detail)
        if (!code && !label && !status && !detail) {
          return null
        }

        return {
          key: `${code || label || 'stage'}-${index + 1}`,
          code,
          label: label || `阶段 ${index + 1}`,
          status,
          detail,
          isCurrent: Boolean(currentStageCode) && code === currentStageCode,
        }
      })
      .filter((item): item is AliasGenerationTestDisplayStage => item !== null)
  }

  if (!Array.isArray(response.steps) || response.steps.length === 0) {
    return []
  }

  return response.steps
    .map((step, index, allSteps) => {
      const code = stringifyFieldValue(step)
      if (!code) {
        return null
      }

      const isLastStep = index === allSteps.length - 1
      return {
        key: `${code}-${index + 1}`,
        code,
        label: normalizeAliasGenerationStageLabel(code, ''),
        status: !response.ok && isLastStep ? 'error' : 'completed',
        detail: '',
        isCurrent: Boolean(currentStageCode) && code === currentStageCode,
      }
    })
    .filter((item): item is AliasGenerationTestDisplayStage => item !== null)
}

function normalizeAliasGenerationFailure(
  response: AliasGenerationTestResponse,
  currentStage: { code: string; label: string },
  stages: AliasGenerationTestDisplayStage[],
): AliasGenerationTestDisplay['failure'] {
  const failure = asRecord(response.failure)
  let stageCode = stringifyFieldValue(failure?.stageCode)
  let stageLabel = stringifyFieldValue(failure?.stageLabel)
  let reason = stringifyFieldValue(failure?.reason)

  if (!stageCode && currentStage.code && (!response.ok || reason)) {
    stageCode = currentStage.code
  }
  if (!stageLabel && currentStage.label && (!response.ok || reason)) {
    stageLabel = currentStage.label
  }

  if ((!stageCode || !stageLabel) && stages.length > 0 && !response.ok) {
    const lastStage = stages[stages.length - 1]
    stageCode ||= lastStage?.code || ''
    stageLabel ||= lastStage?.label || ''
  }

  stageLabel = normalizeAliasGenerationStageLabel(stageCode, stageLabel)

  if (!reason && !response.ok) {
    reason = stringifyFieldValue(response.error)
  }

  const normalizedFailure: AliasGenerationTestDisplay['failure'] = {
    stageCode,
    stageLabel,
    reason,
  }

  if (typeof failure?.retryable === 'boolean') {
    normalizedFailure.retryable = failure.retryable
  }

  return normalizedFailure
}

export function buildAliasGenerationTestDisplay(
  response: AliasGenerationTestResponse,
): AliasGenerationTestDisplay {
  const currentStage = normalizeAliasGenerationCurrentStage(response.currentStage)
  const aliases = normalizeAliasGenerationAliases(response)
  const stages = normalizeAliasGenerationStages(response, currentStage.code)
  const resolvedCurrentStage = currentStage.label || currentStage.code
    ? currentStage
    : stages[stages.length - 1]
      ? {
          code: stages[stages.length - 1].code,
          label: stages[stages.length - 1].label,
        }
      : { code: '', label: '' }
  const failure = normalizeAliasGenerationFailure(response, resolvedCurrentStage, stages)

  return {
    ok: response.ok,
    sourceId: stringifyFieldValue(response.sourceId),
    sourceType: stringifyFieldValue(response.sourceType),
    summaryAliasEmail: aliases[0]?.email || stringifyFieldValue(response.aliasEmail),
    account: normalizeAliasGenerationAccount(response),
    aliases,
    currentStage: resolvedCurrentStage,
    stages,
    failure,
    captureSummary: Array.isArray(response.captureSummary)
      ? response.captureSummary.filter((item): item is Record<string, unknown> => Boolean(asRecord(item)))
      : [],
    logs: Array.isArray(response.logs)
      ? response.logs.map((item) => stringifyFieldValue(item)).filter(Boolean)
      : [],
    error: stringifyFieldValue(response.error),
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function stringifyFieldValue(value: unknown): string {
  if (typeof value === 'string') {
    return value.trim()
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return ''
}

function normalizeMultilineValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => stringifyFieldValue(item))
      .filter(Boolean)
      .join('\n')
  }
  return stringifyFieldValue(value)
}

function normalizeNumericFieldValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) {
      return undefined
    }
    const parsed = Number(trimmed)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }

  return undefined
}

function normalizeAliasGenerationDraftSource(
  value: unknown,
  index: number,
): AliasGenerationTestDraftSource | null {
  const source = asRecord(value)
  if (!source) {
    return null
  }

  const sourceType = stringifyFieldValue(source.type)
  if (
    sourceType !== 'static_list'
    && sourceType !== 'simple_generator'
    && sourceType !== 'vend_email'
  ) {
    return null
  }

  const sourceId = stringifyFieldValue(source.id) || `source-${index + 1}`

  if (sourceType === 'static_list') {
    return {
      id: sourceId,
      type: 'static_list',
      emails: normalizeMultilineValue(source.emails),
    }
  }

  if (sourceType === 'simple_generator') {
    return {
      id: sourceId,
      type: 'simple_generator',
      prefix: stringifyFieldValue(source.prefix),
      suffix: stringifyFieldValue(source.suffix),
      count: normalizeNumericFieldValue(source.count),
      middle_length_min: normalizeNumericFieldValue(source.middle_length_min),
      middle_length_max: normalizeNumericFieldValue(source.middle_length_max),
    }
  }

  return {
    id: sourceId,
    type: 'vend_email',
    register_url: stringifyFieldValue(source.register_url),
    cloudmail_api_base: stringifyFieldValue(source.cloudmail_api_base),
    cloudmail_admin_email: stringifyFieldValue(source.cloudmail_admin_email),
    cloudmail_admin_password: stringifyFieldValue(source.cloudmail_admin_password),
    cloudmail_domain: stringifyFieldValue(source.cloudmail_domain),
    cloudmail_subdomain: stringifyFieldValue(source.cloudmail_subdomain),
    cloudmail_timeout: normalizeNumericFieldValue(source.cloudmail_timeout),
    alias_domain: stringifyFieldValue(source.alias_domain),
    alias_domain_id: stringifyFieldValue(source.alias_domain_id),
    alias_count: normalizeNumericFieldValue(source.alias_count),
    state_key: stringifyFieldValue(source.state_key),
  }
}

export function normalizeAliasGenerationDraftSources(
  value: unknown,
): AliasGenerationTestDraftSource[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .map((item, index) => normalizeAliasGenerationDraftSource(item, index))
    .filter((item): item is AliasGenerationTestDraftSource => item !== null)
}

export function parseStoredAliasGenerationSources(
  value: unknown,
): AliasGenerationTestDraftSource[] {
  if (Array.isArray(value)) {
    return normalizeAliasGenerationDraftSources(value)
  }

  if (typeof value !== 'string') {
    return []
  }

  const trimmed = value.trim()
  if (!trimmed) {
    return []
  }

  try {
    const parsed = JSON.parse(trimmed)
    return normalizeAliasGenerationDraftSources(parsed)
  } catch {
    return []
  }
}

export function serializeAliasGenerationDraftSources(value: unknown): string {
  return JSON.stringify(normalizeAliasGenerationDraftSources(value))
}

function isAliasGenerationDraftSource(
  value: unknown,
): value is AliasGenerationTestDraftSource {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function findDraftSourceByType(
  sources: AliasGenerationTestDraftSource[],
  type: AliasGenerationSourceType,
): AliasGenerationTestDraftSource | null {
  return sources.find((source) => source.type === type) ?? null
}

function buildVendDraftSource(
  draftConfig: AliasGenerationTestDraftConfig,
  preservedSource: AliasGenerationTestDraftSource | null,
): AliasGenerationTestDraftSource | null {
  const vendEnabled =
    typeof draftConfig.cloudmail_alias_vend_enabled === 'undefined'
      ? preservedSource?.type === 'vend_email'
        || parseBooleanConfigValue(draftConfig.cloudmail_alias_service_vend_enabled)
      : parseBooleanConfigValue(draftConfig.cloudmail_alias_vend_enabled)

  if (!vendEnabled) {
    return null
  }

  const sourceId =
    stringifyFieldValue(draftConfig.cloudmail_alias_vend_source_id)
    || stringifyFieldValue(draftConfig.cloudmail_alias_service_vend_source_id)
    || stringifyFieldValue(preservedSource?.id)
    || 'vend-email-primary'

  return {
    id: sourceId,
    type: 'vend_email',
    register_url: stringifyFieldValue(preservedSource?.register_url),
    cloudmail_api_base: stringifyFieldValue(preservedSource?.cloudmail_api_base),
    cloudmail_admin_email: stringifyFieldValue(preservedSource?.cloudmail_admin_email),
    cloudmail_admin_password: stringifyFieldValue(preservedSource?.cloudmail_admin_password),
    cloudmail_domain: stringifyFieldValue(preservedSource?.cloudmail_domain),
    cloudmail_subdomain: stringifyFieldValue(preservedSource?.cloudmail_subdomain),
    cloudmail_timeout: normalizeNumericFieldValue(preservedSource?.cloudmail_timeout),
    alias_domain: stringifyFieldValue(preservedSource?.alias_domain),
    alias_domain_id: stringifyFieldValue(preservedSource?.alias_domain_id),
    alias_count:
      normalizeNumericFieldValue(draftConfig.cloudmail_alias_vend_alias_count)
      ?? normalizeNumericFieldValue(draftConfig.cloudmail_alias_service_vend_alias_count)
      ?? normalizeNumericFieldValue(preservedSource?.alias_count),
    state_key:
      stringifyFieldValue(draftConfig.cloudmail_alias_vend_state_key)
      || stringifyFieldValue(draftConfig.cloudmail_alias_service_vend_state_key)
      || stringifyFieldValue(draftConfig.cloudmail_alias_service_vend_source_id)
      || stringifyFieldValue(preservedSource?.state_key)
      || sourceId,
  }
}

function buildLegacyStaticDraftSource(
  draftConfig: AliasGenerationTestDraftConfig,
  preservedSource: AliasGenerationTestDraftSource | null,
): AliasGenerationTestDraftSource | null {
  const normalizedEmails = normalizeMultilineValue(draftConfig.cloudmail_alias_emails)
  const staticEnabled =
    typeof draftConfig.cloudmail_alias_service_static_enabled === 'undefined'
      ? Boolean(normalizedEmails)
        || !parseBooleanConfigValue(draftConfig.cloudmail_alias_vend_enabled)
      : parseBooleanConfigValue(draftConfig.cloudmail_alias_service_static_enabled)

  if (!staticEnabled || !normalizedEmails) {
    return null
  }

  return {
    id: stringifyFieldValue(preservedSource?.id) || 'legacy-static',
    type: 'static_list',
    emails: normalizedEmails,
  }
}

export function deriveAliasGenerationDraftSources(
  draftConfig: AliasGenerationTestDraftConfig,
): AliasGenerationTestDraftSource[] {
  if (!parseBooleanConfigValue(draftConfig.cloudmail_alias_enabled)) {
    return []
  }

  const normalizedSources = normalizeAliasGenerationDraftSources(draftConfig.sources)
  const staticSource = buildLegacyStaticDraftSource(
    draftConfig,
    findDraftSourceByType(normalizedSources, 'static_list'),
  )
  const vendSource = buildVendDraftSource(
    draftConfig,
    findDraftSourceByType(normalizedSources, 'vend_email'),
  )
  const preservedOtherSources = normalizedSources.filter((source) => (
    source.type !== 'static_list'
    && source.type !== 'vend_email'
  ))

  return [...preservedOtherSources, staticSource, vendSource].filter(
    (source): source is AliasGenerationTestDraftSource => source !== null,
  )
}

export function deriveCloudmailAliasServiceFormValues(
  draftConfig: AliasGenerationTestDraftConfig,
): Pick<
  AliasGenerationTestDraftConfig,
  | 'cloudmail_alias_enabled'
  | 'cloudmail_alias_emails'
  | 'cloudmail_alias_vend_enabled'
  | 'cloudmail_alias_vend_alias_count'
  | 'cloudmail_alias_vend_source_id'
  | 'cloudmail_alias_vend_state_key'
> {
  const normalizedSources = normalizeAliasGenerationDraftSources(draftConfig.sources)
  const vendSource = findDraftSourceByType(normalizedSources, 'vend_email')
  const staticSource = findDraftSourceByType(normalizedSources, 'static_list')
  const normalizedEmails = normalizeMultilineValue(staticSource?.emails)
  const hasExistingAliasEnabledValue =
    typeof draftConfig.cloudmail_alias_enabled !== 'undefined'
      && String(draftConfig.cloudmail_alias_enabled).trim() !== ''

  return {
    cloudmail_alias_enabled: hasExistingAliasEnabledValue
      ? draftConfig.cloudmail_alias_enabled
      : normalizedSources.length > 0,
    cloudmail_alias_emails:
      normalizeMultilineValue(draftConfig.cloudmail_alias_emails) || normalizedEmails,
    cloudmail_alias_vend_enabled:
      typeof draftConfig.cloudmail_alias_vend_enabled === 'undefined'
        ? Boolean(vendSource) || parseBooleanConfigValue(draftConfig.cloudmail_alias_service_vend_enabled)
        : draftConfig.cloudmail_alias_vend_enabled,
    cloudmail_alias_vend_alias_count:
      normalizeNumericFieldValue(draftConfig.cloudmail_alias_vend_alias_count)
      ?? normalizeNumericFieldValue(vendSource?.alias_count)
      ?? normalizeNumericFieldValue(draftConfig.cloudmail_alias_service_vend_alias_count),
    cloudmail_alias_vend_source_id:
      stringifyFieldValue(draftConfig.cloudmail_alias_service_vend_source_id)
      || stringifyFieldValue(vendSource?.id),
    cloudmail_alias_vend_state_key:
      stringifyFieldValue(draftConfig.cloudmail_alias_service_vend_state_key)
      || stringifyFieldValue(vendSource?.state_key),
  }
}

export function createAliasGenerationTestDraftConfig(
  formValues: Record<string, unknown>,
): AliasGenerationTestDraftConfig {
  const vendEnabled = parseBooleanConfigValue(formValues.cloudmail_alias_vend_enabled)
  const vendAliasCount = formValues.cloudmail_alias_vend_alias_count
  const vendSourceId = formValues.cloudmail_alias_vend_source_id
  const vendStateKey = formValues.cloudmail_alias_vend_state_key

  return {
    cloudmail_alias_enabled: formValues.cloudmail_alias_enabled,
    cloudmail_alias_emails: formValues.cloudmail_alias_emails,
    cloudmail_alias_service_static_enabled:
      typeof formValues.cloudmail_alias_service_static_enabled === 'undefined'
        ? parseBooleanConfigValue(formValues.cloudmail_alias_enabled)
        : formValues.cloudmail_alias_service_static_enabled,
    cloudmail_alias_service_simple_enabled: formValues.cloudmail_alias_service_simple_enabled,
    cloudmail_alias_service_simple_prefix: formValues.cloudmail_alias_service_simple_prefix,
    cloudmail_alias_service_simple_suffix: formValues.cloudmail_alias_service_simple_suffix,
    cloudmail_alias_service_simple_count: formValues.cloudmail_alias_service_simple_count,
    cloudmail_alias_service_simple_middle_length_min: formValues.cloudmail_alias_service_simple_middle_length_min,
    cloudmail_alias_service_simple_middle_length_max: formValues.cloudmail_alias_service_simple_middle_length_max,
    cloudmail_alias_vend_enabled: formValues.cloudmail_alias_vend_enabled,
    cloudmail_alias_vend_alias_count: vendAliasCount,
    cloudmail_alias_vend_source_id: vendSourceId,
    cloudmail_alias_vend_state_key: vendStateKey,
    cloudmail_alias_service_vend_enabled:
      typeof formValues.cloudmail_alias_service_vend_enabled === 'undefined'
        ? vendEnabled
        : formValues.cloudmail_alias_service_vend_enabled,
    cloudmail_alias_service_vend_alias_count:
      typeof formValues.cloudmail_alias_service_vend_alias_count === 'undefined'
        ? vendAliasCount
        : formValues.cloudmail_alias_service_vend_alias_count,
    cloudmail_alias_service_vend_source_id:
      typeof formValues.cloudmail_alias_service_vend_source_id === 'undefined'
        ? vendSourceId
        : formValues.cloudmail_alias_service_vend_source_id,
    cloudmail_alias_service_vend_state_key:
      typeof formValues.cloudmail_alias_service_vend_state_key === 'undefined'
        ? vendStateKey
        : formValues.cloudmail_alias_service_vend_state_key,
    sources: deriveAliasGenerationDraftSources(formValues),
  }
}

function extractExplicitAliasGenerationSourceOptions(
  draftConfig: AliasGenerationTestDraftConfig,
): AliasGenerationSourceOption[] {
  return normalizeAliasGenerationDraftSources(draftConfig.sources)
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
      description: 'alias source 列表与测试请求都使用当前 CloudMail 未保存配置。',
      emptyDescription: '请先在当前表单中启用 CloudMail 别名，并配置 legacy 别名列表或开启可用服务。',
      sourceOptions: draftSourceOptions,
    }
  }

  return {
    configMode: 'saved',
    configLabel: '已保存配置',
    description: 'alias source 列表与测试请求都使用已保存的 CloudMail 配置；未保存表单改动不会参与这次测试。',
    emptyDescription: '已保存配置中没有可测试的 alias source。请先保存 CloudMail 别名配置，或切换为使用当前未保存表单值测试。',
    sourceOptions: savedSourceOptions,
  }
}

export async function runAliasGenerationTest(
  payload: AliasGenerationTestRequest,
): Promise<AliasGenerationTestResponse> {
  const shouldUseProvidedConfig = Boolean(payload.config)

  return apiFetch('/config/alias-test', {
    method: 'POST',
    body: JSON.stringify({
      sourceId: payload.sourceId,
      useDraftConfig: shouldUseProvidedConfig ? true : payload.useDraftConfig,
      config: shouldUseProvidedConfig ? payload.config : undefined,
    }),
  })
}
