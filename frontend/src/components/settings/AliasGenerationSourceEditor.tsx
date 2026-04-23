import { PlusOutlined } from '@ant-design/icons'
import { useMemo, useState } from 'react'
import { Button, Card, Empty, Form, Select, Space, Typography } from 'antd'
import type { FormInstance } from 'antd'

import AliasGenerationSourceCard from '@/components/settings/AliasGenerationSourceCard'
import {
  ADDABLE_ALIAS_GENERATION_SOURCE_TYPES,
  createAliasGenerationDraftSourceTemplate,
  getAliasGenerationSourceTypeLabel,
  normalizeAliasGenerationDraftSources,
  type AliasGenerationSourceType,
} from '@/lib/aliasGenerationTest'

type Props = {
  form: FormInstance
}

const LEGACY_MANAGED_SOURCE_TYPES = new Set(['static_list', 'vend_email', 'alias_email'])

export default function AliasGenerationSourceEditor({ form }: Props) {
  const watchedSources = Form.useWatch('sources', form)
  const [nextSourceType, setNextSourceType] = useState<AliasGenerationSourceType>(
    ADDABLE_ALIAS_GENERATION_SOURCE_TYPES[0] ?? 'simple_generator',
  )

  const normalizedSources = useMemo(
    () => normalizeAliasGenerationDraftSources(watchedSources),
    [watchedSources],
  )

  const editableEntries = useMemo(
    () => normalizedSources
      .map((source, index) => ({ source, index }))
      .filter(({ source }) => !LEGACY_MANAGED_SOURCE_TYPES.has(String(source.type || '').trim())),
    [normalizedSources],
  )

  const addOptions = useMemo(
    () => ADDABLE_ALIAS_GENERATION_SOURCE_TYPES.map((type) => ({
      label: getAliasGenerationSourceTypeLabel(type),
      value: type,
    })),
    [],
  )

  const handleAddSource = () => {
    form.setFieldValue('sources', [
      ...normalizedSources,
      createAliasGenerationDraftSourceTemplate(nextSourceType),
    ])
  }

  const handleRemoveSource = (index: number) => {
    form.setFieldValue(
      'sources',
      normalizedSources.filter((_source, sourceIndex) => sourceIndex !== index),
    )
  }

  const handleChangeSourceType = (
    index: number,
    nextType: AliasGenerationSourceType,
  ) => {
    const nextSources = [...normalizedSources]
    const currentSourceId = String(nextSources[index]?.id || '').trim()

    nextSources[index] = createAliasGenerationDraftSourceTemplate(
      nextType,
      currentSourceId,
    )

    form.setFieldValue('sources', nextSources)
  }

  return (
    <Card
      title="Alias Source 编辑器"
      extra={<span style={{ fontSize: 12, color: '#7a8ba3' }}>为 interactive providers 和额外生成器维护最小 source 配置</span>}
      style={{ marginBottom: 16 }}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          上方 legacy 别名列表与 vend 开关仍然会自动同步到 alias 池；这里仅编辑额外 source，并保持整个 `sources` 字段的保存/读取 round-trip 不变。
        </Typography.Text>

        {editableEntries.length > 0 ? (
          editableEntries.map(({ source, index }) => (
            <AliasGenerationSourceCard
              key={`${String(source.id || 'source').trim() || 'source'}-${index}`}
              index={index}
              source={source}
              onRemove={() => handleRemoveSource(index)}
              onTypeChange={(value) => handleChangeSourceType(index, value)}
            />
          ))
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="当前还没有额外 alias source；可在下方添加 interactive provider 或 simple generator。"
          />
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(240px, 320px) auto',
            gap: 12,
            alignItems: 'end',
          }}
        >
          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
              新增 source 类型
            </Typography.Text>
            <Select
              value={nextSourceType}
              options={addOptions}
              onChange={(value) => setNextSourceType(value as AliasGenerationSourceType)}
            />
          </div>

          <Button type="dashed" icon={<PlusOutlined />} onClick={handleAddSource}>
            添加 source
          </Button>
        </div>
      </Space>
    </Card>
  )
}
