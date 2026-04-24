import {
  buildAliasGenerationTestDisplay,
  createAliasGenerationTestDraftConfig,
  deriveCloudmailAliasServiceFormValues,
  type AliasGenerationSourceType,
  type AliasGenerationTestDraftSource,
  type AliasGenerationTestResponse,
} from '@/lib/aliasGenerationTest'

const providerTypes: AliasGenerationSourceType[] = [
  'static_list',
  'simple_generator',
  'vend_email',
  'myalias_pro',
  'secureinseconds',
  'emailshield',
  'simplelogin',
  'alias_email',
]

const simpleLoginSource: AliasGenerationTestDraftSource = {
  id: 'simplelogin-primary',
  type: 'simplelogin',
  alias_count: 3,
  low_watermark: 2,
  single_account_alias_count: 10,
  state_key: 'simplelogin-primary',
  provider_config: {
    site_url: 'https://simplelogin.io/',
    accounts: [
      { email: 'fust@fst.cxwsss.online', label: 'fust' },
      { email: 'logon@fst.cxwsss.online', label: 'logon', password: 'logon@fst.cxwsss.online' },
    ],
  },
}

const interactiveResponse: AliasGenerationTestResponse = {
  ok: true,
  sourceId: 'simplelogin-primary',
  sourceType: 'simplelogin',
  aliasEmail: 'sisyrun0419a.relearn763@aleeas.com',
  realMailboxEmail: 'fust@fst.cxwsss.online',
  serviceEmail: 'fust@fst.cxwsss.online',
  accountIdentity: {
    serviceAccountEmail: 'fust@fst.cxwsss.online',
    realMailboxEmail: 'fust@fst.cxwsss.online',
    servicePassword: 'fust@fst.cxwsss.online',
    username: 'fust',
  },
  aliases: [
    { email: 'sisyrun0419a.relearn763@aleeas.com' },
    { email: 'sisyrun0419b.onion376@simplelogin.com' },
    { email: 'sisyrun0419c.skies135@slmails.com' },
  ],
  currentStage: { code: 'discover_alias_domains', label: '发现可用域名' },
  stages: [
    { code: 'select_service_account', label: '选择服务账号', status: 'completed' },
    { code: 'login_submit', label: '登录服务账号', status: 'completed' },
    { code: 'discover_alias_domains', label: '发现可用域名', status: 'completed' },
    { code: 'create_aliases', label: '创建别名', status: 'completed' },
  ],
  failure: { stageCode: '', stageLabel: '', reason: '' },
  captureSummary: [],
  steps: [],
  logs: [],
  error: '',
}

const modernResponse: AliasGenerationTestResponse = {
  ok: true,
  sourceId: 'vend-email-primary',
  sourceType: 'vend_email',
  aliasEmail: 'alias-001@vend.example',
  realMailboxEmail: 'real@example.com',
  serviceEmail: 'service-account@vend.example',
  accountIdentity: {
    serviceAccountEmail: 'service-account@vend.example',
    confirmationInboxEmail: 'service-account@vend.example',
    realMailboxEmail: 'real@example.com',
    servicePassword: 'vend-secret',
    username: 'vend-demo',
  },
  account: {
    realMailboxEmail: 'real@example.com',
    serviceEmail: 'service-account@vend.example',
    password: 'vend-secret',
    username: 'vend-demo',
  },
  aliases: [
    { email: 'alias-001@vend.example' },
    { email: 'alias-002@vend.example' },
    { email: 'alias-003@vend.example' },
  ],
  currentStage: {
    code: 'aliases_ready',
    label: '别名预览已生成',
  },
  stages: [
    { code: 'register_submit', label: '注册表单提交', status: 'ok' },
    { code: 'fetch_confirmation_mail', label: '查找确认邮件', status: 'ok' },
    { code: 'open_confirmation_link', label: '打开确认链接', status: 'ok' },
    { code: 'list_aliases', label: '列出现有别名', status: 'ok' },
    { code: 'create_aliases', label: '创建别名', status: 'ok', detail: '已补齐 3 个别名' },
  ],
  failure: {
    stageCode: '',
    stageLabel: '',
    reason: '',
  },
  captureSummary: [{ name: 'capture-1' }],
  steps: ['load_source', 'acquire_alias'],
  logs: ['alias probe ok'],
  error: '',
}

const legacyResponse: AliasGenerationTestResponse = {
  ok: false,
  sourceId: 'legacy-static',
  sourceType: 'static_list',
  aliasEmail: 'legacy@example.com',
  realMailboxEmail: 'real@example.com',
  serviceEmail: '',
  captureSummary: [],
  steps: ['load_source', 'acquire_alias'],
  logs: ['legacy failed'],
  error: 'legacy error',
}

const modernDisplay = buildAliasGenerationTestDisplay(modernResponse)
const legacyDisplay = buildAliasGenerationTestDisplay(legacyResponse)
const interactiveDisplay = buildAliasGenerationTestDisplay(interactiveResponse)

const fixedServiceDraftConfig = createAliasGenerationTestDraftConfig({
  cloudmail_alias_enabled: true,
  cloudmail_alias_emails: 'legacy@example.com',
  cloudmail_alias_vend_enabled: true,
  cloudmail_alias_vend_alias_count: 2,
  cloudmail_alias_vend_low_watermark: 1,
  cloudmail_alias_myalias_pro_enabled: true,
  cloudmail_alias_myalias_pro_alias_count: 3,
  cloudmail_alias_myalias_pro_low_watermark: 1,
  cloudmail_alias_secureinseconds_enabled: true,
  cloudmail_alias_secureinseconds_source_id: 'secureinseconds-primary',
  cloudmail_alias_secureinseconds_state_key: 'secureinseconds-state',
  cloudmail_alias_secureinseconds_alias_count: 4,
  cloudmail_alias_secureinseconds_low_watermark: 2,
  cloudmail_alias_secureinseconds_register_url: 'https://alias.secureinseconds.com/auth/register',
  cloudmail_alias_secureinseconds_login_url: 'https://alias.secureinseconds.com/auth/signin',
  cloudmail_alias_secureinseconds_confirmation_email: 'real@example.com',
  cloudmail_alias_secureinseconds_confirmation_password: 'mail-pass',
  cloudmail_alias_secureinseconds_match_email: 'real@example.com',
  cloudmail_alias_emailshield_enabled: true,
  cloudmail_alias_emailshield_source_id: 'emailshield-primary',
  cloudmail_alias_emailshield_state_key: 'emailshield-state',
  cloudmail_alias_emailshield_alias_count: 5,
  cloudmail_alias_emailshield_low_watermark: 2,
  cloudmail_alias_emailshield_single_account_alias_count: 8,
  cloudmail_alias_emailshield_accounts: 'loga@fst.cxwsss.online\njuso@fst.cxwsss.online',
  cloudmail_alias_simplelogin_enabled: true,
  cloudmail_alias_simplelogin_source_id: 'simplelogin-primary',
  cloudmail_alias_simplelogin_state_key: 'simplelogin-state',
  cloudmail_alias_simplelogin_alias_count: 3,
  cloudmail_alias_simplelogin_low_watermark: 2,
  cloudmail_alias_simplelogin_single_account_alias_count: 10,
  cloudmail_alias_simplelogin_site_url: 'https://simplelogin.io/',
  cloudmail_alias_simplelogin_accounts: 'fust@fst.cxwsss.online\nlogon@fst.cxwsss.online',
  cloudmail_alias_alias_email_enabled: true,
  cloudmail_alias_alias_email_source_id: 'alias-email-primary',
  cloudmail_alias_alias_email_state_key: 'alias-email-state',
  cloudmail_alias_alias_email_alias_count: 3,
  cloudmail_alias_alias_email_low_watermark: 1,
  cloudmail_alias_alias_email_login_url: 'https://alias.email/users/login/',
  cloudmail_alias_alias_email_match_email: 'real@example.com',
})

const fixedServiceRoundTrip = deriveCloudmailAliasServiceFormValues({
  cloudmail_alias_enabled: true,
  sources: fixedServiceDraftConfig.sources,
})

const hiddenSimpleGeneratorDraftConfig = createAliasGenerationTestDraftConfig({
  cloudmail_alias_enabled: true,
  cloudmail_alias_emails: 'legacy@example.com',
  sources: [
    {
      id: 'hidden-simple-generator',
      type: 'simple_generator',
      prefix: 'msi.',
      suffix: '@example.com',
      count: 2,
      middle_length_min: 3,
      middle_length_max: 6,
    },
  ],
})

const hiddenSimpleGeneratorRoundTrip = deriveCloudmailAliasServiceFormValues({
  cloudmail_alias_enabled: true,
  sources: hiddenSimpleGeneratorDraftConfig.sources,
})

const hiddenSimpleGeneratorSourceCount = Array.isArray(hiddenSimpleGeneratorDraftConfig.sources)
  ? hiddenSimpleGeneratorDraftConfig.sources.length
  : -1

const hiddenSimpleGeneratorRejected = hiddenSimpleGeneratorSourceCount === 0

const noStaticAliasDraftConfig = createAliasGenerationTestDraftConfig({
  cloudmail_alias_enabled: true,
  cloudmail_alias_emails: '',
  cloudmail_alias_vend_enabled: true,
})

const noStaticAliasSourceTypes = Array.isArray(noStaticAliasDraftConfig.sources)
  ? noStaticAliasDraftConfig.sources.map((source) => String(source?.type || ''))
  : []

void [
  providerTypes,
  simpleLoginSource,
  fixedServiceDraftConfig.sources,
  fixedServiceRoundTrip.cloudmail_alias_myalias_pro_enabled,
  fixedServiceRoundTrip.cloudmail_alias_myalias_pro_alias_count,
  fixedServiceRoundTrip.cloudmail_alias_myalias_pro_low_watermark,
  fixedServiceRoundTrip.cloudmail_alias_secureinseconds_enabled,
  fixedServiceRoundTrip.cloudmail_alias_secureinseconds_low_watermark,
  fixedServiceRoundTrip.cloudmail_alias_emailshield_enabled,
  fixedServiceRoundTrip.cloudmail_alias_emailshield_low_watermark,
  fixedServiceRoundTrip.cloudmail_alias_emailshield_single_account_alias_count,
  fixedServiceRoundTrip.cloudmail_alias_simplelogin_enabled,
  fixedServiceRoundTrip.cloudmail_alias_simplelogin_low_watermark,
  fixedServiceRoundTrip.cloudmail_alias_simplelogin_single_account_alias_count,
  fixedServiceRoundTrip.cloudmail_alias_alias_email_enabled,
  fixedServiceRoundTrip.cloudmail_alias_alias_email_low_watermark,
  fixedServiceRoundTrip.cloudmail_alias_emailshield_accounts,
  fixedServiceRoundTrip.cloudmail_alias_simplelogin_accounts,
  hiddenSimpleGeneratorDraftConfig.sources,
  hiddenSimpleGeneratorRejected,
  hiddenSimpleGeneratorRoundTrip.cloudmail_alias_simplelogin_enabled,
  noStaticAliasSourceTypes,
  modernDisplay.summaryAliasEmail,
  modernDisplay.account.realMailboxEmail,
  modernDisplay.account.serviceEmail,
  modernDisplay.account.password,
  modernDisplay.account.username,
  modernDisplay.aliases[2]?.email,
  modernDisplay.currentStage.label,
  modernDisplay.stages[4]?.detail,
  modernDisplay.failure.reason,
  modernDisplay.captureSummary[0]?.name,
  legacyDisplay.summaryAliasEmail,
  legacyDisplay.aliases[0]?.email,
  legacyDisplay.stages[0]?.label,
  legacyDisplay.failure.reason,
  interactiveDisplay.currentStage.label,
  interactiveDisplay.stages[2]?.label,
  interactiveDisplay.aliases[2]?.email,
]

export {}
