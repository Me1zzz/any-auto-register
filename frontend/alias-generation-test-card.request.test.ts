// @vitest-environment jsdom

import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import AliasGenerationTestCard from '@/components/settings/AliasGenerationTestCard'
import type {
  AliasGenerationSourceOption,
  AliasGenerationTestDraftConfig,
  AliasGenerationTestResponse,
} from '@/lib/aliasGenerationTest'
import { apiFetch } from '@/lib/utils'

vi.mock('@/lib/utils', () => ({
  apiFetch: vi.fn(),
}))

const mockedApiFetch = vi.mocked(apiFetch)

const MYALIAS_SOURCE_OPTIONS: AliasGenerationSourceOption[] = [
  { id: 'myalias-pro-primary', type: 'myalias_pro' },
]

const MYALIAS_DRAFT_CONFIG: AliasGenerationTestDraftConfig = {
  cloudmail_alias_enabled: true,
  cloudmail_alias_emails: '',
  cloudmail_alias_service_static_enabled: true,
  cloudmail_alias_vend_enabled: false,
  cloudmail_alias_myalias_pro_enabled: true,
  cloudmail_alias_secureinseconds_enabled: false,
  cloudmail_alias_emailshield_enabled: false,
  cloudmail_alias_simplelogin_enabled: false,
  cloudmail_alias_alias_email_enabled: false,
  cloudmail_alias_service_vend_enabled: false,
  sources: [
    {
      id: 'myalias-pro-primary',
      type: 'myalias_pro',
      alias_count: 3,
      state_key: 'myalias-pro-primary',
      provider_config: {
        signup_url: 'https://myalias.pro/signup/',
        login_url: 'https://myalias.pro/login/',
        alias_url: 'https://myalias.pro/aliases/',
      },
      confirmation_inbox: {
        provider: 'cloudmail',
      },
    },
  ],
}

const SUCCESS_RESPONSE: AliasGenerationTestResponse = {
  ok: true,
  sourceId: 'myalias-pro-primary',
  sourceType: 'myalias_pro',
  aliasEmail: 'alias@example.com',
  realMailboxEmail: 'real@example.com',
  serviceEmail: 'service@example.com',
  account: {
    realMailboxEmail: 'real@example.com',
    serviceEmail: 'service@example.com',
    password: 'secret',
  },
  aliases: [{ email: 'alias@example.com' }],
  currentStage: {
    code: 'aliases_ready',
    label: '别名预览已生成',
  },
  stages: [
    {
      code: 'aliases_ready',
      label: '别名预览已生成',
      status: 'completed',
      detail: '',
    },
  ],
  failure: {},
  captureSummary: [],
  steps: ['aliases_ready'],
  logs: [],
  error: '',
}

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })

  vi.stubGlobal(
    'ResizeObserver',
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )

  Element.prototype.scrollIntoView = vi.fn()
})

beforeEach(() => {
  mockedApiFetch.mockReset()
  mockedApiFetch.mockResolvedValue(SUCCESS_RESPONSE)
})

afterEach(() => {
  cleanup()
})

describe('AliasGenerationTestCard request path', () => {
  it('invokes /config/alias-test for the current MyAlias draft config shape', async () => {
    render(
      React.createElement(AliasGenerationTestCard, {
        draftConfig: MYALIAS_DRAFT_CONFIG,
        draftSourceOptions: MYALIAS_SOURCE_OPTIONS,
        savedSourceOptions: [],
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: '测试生成别名邮箱' }))

    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledTimes(1)
    })

    const [path, requestInit] = mockedApiFetch.mock.calls[0] ?? []

    expect(path).toBe('/config/alias-test')
    expect(requestInit?.method).toBe('POST')
    expect(JSON.parse(String(requestInit?.body))).toEqual({
      sourceId: 'myalias-pro-primary',
      useDraftConfig: true,
      config: MYALIAS_DRAFT_CONFIG,
    })
  })
})
