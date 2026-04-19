import {
  buildAliasGenerationTestDisplay,
  type AliasGenerationTestResponse,
} from '@/lib/aliasGenerationTest'

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

void [
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
]

export {}
