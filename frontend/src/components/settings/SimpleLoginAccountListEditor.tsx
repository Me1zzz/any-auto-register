import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Form, Input, Space, Typography } from 'antd'

type Props = {
  name: (string | number)[]
}

export default function SimpleLoginAccountListEditor({ name }: Props) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {fields.map((field) => (
            <div
              key={field.key}
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr)) auto',
                gap: 8,
                alignItems: 'start',
              }}
            >
              <Form.Item
                label="账号邮箱"
                name={[field.name, 'email']}
                rules={[{ required: true, message: '请输入账号邮箱' }]}
                style={{ marginBottom: 0 }}
              >
                <Input placeholder="fust@fst.cxwsss.online" />
              </Form.Item>

              <Form.Item
                label="标签"
                name={[field.name, 'label']}
                style={{ marginBottom: 0 }}
              >
                <Input placeholder="例如：fust" />
              </Form.Item>

              <Form.Item
                label="密码"
                name={[field.name, 'password']}
                style={{ marginBottom: 0 }}
              >
                <Input.Password placeholder="留空时默认等于邮箱" />
              </Form.Item>

              <div style={{ display: 'flex', alignItems: 'end', height: '100%' }}>
                <Button danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)}>
                  删除
                </Button>
              </div>
            </div>
          ))}

          {fields.length === 0 ? (
            <Typography.Text type="secondary">
              还没有配置 SimpleLogin 服务账号。至少添加一个账号后，运行时才能选择服务账号并发现 signed domain options。
            </Typography.Text>
          ) : null}

          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => add({ email: '', label: '', password: '' })}
          >
            添加 SimpleLogin 账号
          </Button>
        </Space>
      )}
    </Form.List>
  )
}
