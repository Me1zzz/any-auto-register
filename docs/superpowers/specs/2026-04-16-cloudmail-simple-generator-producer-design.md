# CloudMail Simple Generator Producer 设计

## 背景

当前 CloudMail alias pool 已经具备 task-scoped pool、source producer 抽象、`StaticAliasListProducer` 和 `AliasServiceProducerBase` 骨架，但还没有一个真正走“service-like source”路径的最小实现。

现有唯一可用来源仍然是 `static_list`：配置中直接给出一组 alias 邮箱，再由 `api/tasks.py` 装载进 `AliasEmailPoolManager`。这能覆盖静态别名场景，但还不能验证 phase-2 新引入的“非静态来源 producer”装配路径是否成立。

本次需求是增加一个**简单的别名邮箱服务 Producer**，它**不做注册、登录、邮箱验证、浏览器自动化**，只按照固定规则生成别名邮箱：

- 固定前缀 `prefix`
- 随机中段 `[a-z0-9]`
- 固定后缀 `suffix`

生成规则参考 `custom_tools/gen.py`：

```python
def generate_string(PREFIX, SUFFIX, MIDDLE_LENGTH=8) -> str:
    middle = ''.join(random.choices(string.ascii_lowercase + string.digits, k=MIDDLE_LENGTH))
    return f"{PREFIX}{middle}{SUFFIX}"
```

## 目标

增加一个最小可用的 `simple_generator` source type，用来验证 alias pool 对“动态生成型来源”的支持能力，同时保持现有 static list 兼容路径不变。

该 source 的职责仅限于：

1. 读取配置中的生成规则
2. 批量生成若干个 alias 邮箱
3. 将生成结果包装为 `AliasEmailLease`
4. 投递到任务级 `AliasEmailPoolManager`

## 非目标

本次不包含以下能力：

- 不实现真实 alias service 网站交互
- 不实现注册、登录、验证码确认、cookie/token/session 维护
- 不实现异步补货线程或后台循环
- 不实现跨任务共享 alias 池
- 不实现新的前端界面
- 不引入新的外部依赖

## 设计原则

### 1. 结构上像 service source，行为上保持最小

这个 producer 的意义不是功能复杂，而是验证“source producer 不一定是静态列表”这条架构路径已经能跑通。因此它应该：

- 作为独立 source type 存在，而不是把随机生成逻辑塞进 `static_list`
- 保持 `AliasServiceProducerBase` 风格的 source 身份
- 在 task 启动阶段一次性把生成结果装进 pool

### 2. 不污染 static list 语义

`static_list` 仍表示“外部已经给定的邮箱集合”，而 `simple_generator` 表示“根据规则即时生成的邮箱集合”。两者配置和语义分离，便于后续继续加入真正的服务型 producer。

### 3. 先验证 producer 装配链路，不提前做 phase-3 复杂度

`simple_generator` 是 phase-2 到 phase-3 之间的桥接实现。它只验证：

- config normalize 能识别新 source
- `_build_alias_pool()` 能实例化新 producer
- producer 能向 pool 正常投递 lease
- `CloudMailMailbox` 能像消费 static list 一样消费它

## 配置模型

新增显式 source type：`simple_generator`

推荐配置结构：

```python
{
  "cloudmail_alias_enabled": True,
  "sources": [
    {
      "id": "simple-1",
      "type": "simple_generator",
      "prefix": "msiabc.",
      "suffix": "@manyme.com",
      "mailbox_email": "admin@example.com",
      "count": 20,
      "middle_length_min": 3,
      "middle_length_max": 6,
    }
  ],
}
```

字段说明：

- `id`: source 标识，缺省时按索引生成默认值
- `type`: 固定为 `simple_generator`
- `prefix`: 别名前缀，可为空字符串
- `suffix`: 别名后缀，通常包含域名，如 `@manyme.com`
- `mailbox_email`: 对应 CloudMail 真实收件邮箱
- `count`: 本次任务初始化时预生成多少个 alias
- `middle_length_min`: 随机中段最小长度
- `middle_length_max`: 随机中段最大长度

### 归一化规则

`core/alias_pool/config.py` 需要扩展 `_normalize_sources()`，除了当前 `static_list` 外，还接受 `simple_generator`。

归一化后输出形状：

```python
{
  "id": "simple-1",
  "type": "simple_generator",
  "prefix": "msiabc.",
  "suffix": "@manyme.com",
  "mailbox_email": "admin@example.com",
  "count": 20,
  "middle_length_min": 3,
  "middle_length_max": 6,
}
```

约束：

- `count <= 0` 时视为不生成任何 alias，但 source 仍可被识别
- `middle_length_min` / `middle_length_max` 都应归一化为整数
- 若 `middle_length_min <= 0`，回退到安全默认值
- 若 `middle_length_max < middle_length_min`，则将上限提升到与下限一致
- `prefix` / `suffix` / `mailbox_email` 统一做字符串清洗

## Producer 设计

### SimpleAliasGeneratorProducer

新增文件：`core/alias_pool/simple_generator.py`

定义一个轻量 producer，例如：

- `source_kind = "simple_generator"`
- 初始化时接收：
  - `source_id`
  - `prefix`
  - `suffix`
  - `mailbox_email`
  - `count`
  - `middle_length_min`
  - `middle_length_max`

### 状态模型

沿用当前 phase-2 producer 状态：

- 初始：`IDLE`
- 开始装载时：`ACTIVE`
- 全部生成完成后：`EXHAUSTED`
- 若生成阶段抛出明确异常：`FAILED`

本次实现不引入后台补货，因此状态迁移与 `StaticAliasListProducer` 类似，只是“装载内容”来自动态生成而不是静态数组。

### 生成逻辑

在 `load_into(manager)` 中：

1. 将状态置为 `ACTIVE`
2. 循环生成 `count` 个 alias
3. 每个 alias 由以下规则拼装：

```text
alias_email = prefix + random_middle + suffix
```

其中 `random_middle`：

- 字符集：`abcdefghijklmnopqrstuvwxyz0123456789`
- 长度：`middle_length_min ~ middle_length_max` 之间的随机值

4. 为每个 alias 构造 `AliasEmailLease`
5. `manager.add_lease(...)`
6. 完成后将状态置为 `EXHAUSTED`

若中途发生异常：

- 将状态置为 `FAILED`
- 异常继续向外抛出，保持与当前最小实现一致

### 去重策略

本次只做**单 producer 单次装载内去重**：

- 同一次 `load_into()` 中，生成结果不能重复
- 不尝试与其他 source 去重
- 不尝试与历史任务去重

这样可以避免随机生成在小样本下出现重复，同时不把本次实现扩展成全局唯一性系统。

## 任务装配路径

`api/tasks.py::_build_alias_pool()` 当前只会根据 `source.type == "static_list"` 实例化 `StaticAliasListProducer`。

本次需要扩展为：

- `static_list` → `StaticAliasListProducer`
- `simple_generator` → `SimpleAliasGeneratorProducer`

统一流程保持不变：

1. 创建 `AliasEmailPoolManager`
2. 遍历 `normalize_cloudmail_alias_pool_config()` 输出的 `sources`
3. 实例化对应 producer
4. `manager.register_source(producer)`
5. `producer.load_into(manager)`

这样 `CloudMailMailbox` 无需修改消费协议，只要拿到的仍然是 `AliasEmailLease` 即可。

## 测试设计

保持现有 `unittest` 风格，在 `tests/test_alias_pool.py` 补充以下覆盖：

1. **config normalize**
   - `simple_generator` source 能被保留
   - `prefix/suffix/mailbox_email/count/length range` 被正确归一化

2. **producer contract**
   - 初始状态为 `IDLE`
   - `load_into()` 后状态为 `EXHAUSTED`
   - 生成出的 lease：
     - `source_kind == "simple_generator"`
     - `source_id` 正确
     - `real_mailbox_email` 正确
     - alias 以 `prefix` 开头、以 `suffix` 结尾

3. **去重行为**
   - 单次生成 `count > 1` 时，不会在本次装载结果中出现重复 alias

4. **task integration**
   - 若 `tests/test_register_task_controls.py` 现有覆盖不足，则补一个最小测试，验证 `_build_alias_pool()` 在 `simple_generator` 配置下确实完成 producer 装载

## 影响范围

### 新增文件

- `core/alias_pool/simple_generator.py`

### 修改文件

- `core/alias_pool/config.py`
- `api/tasks.py`
- `tests/test_alias_pool.py`
- 视现有覆盖情况，可能修改 `tests/test_register_task_controls.py`

## 风险与取舍

### 1. 随机长度与随机内容不可预测

测试不能断言完整邮箱字符串，而应断言：

- 前缀正确
- 后缀正确
- 中段长度落在区间内
- 中段只包含 `[a-z0-9]`

### 2. 去重可能导致生成循环比 `count` 更多次

这是可接受的，因为本次 `count` 规模很小，字符空间足够大。实现上只需要做简单循环重试，不需要复杂退避策略。

### 3. 这个 producer 不是“真实服务”

这是有意为之。它的目标是验证 producer 架构，而不是提前实现 phase-3 浏览器自动化。后续真实服务 producer 可以在这个 source-type 装配路径上继续扩展，但不应复用这个类的业务语义。

## 验收标准

满足以下条件即可认为本次设计落地成功：

1. 配置中可声明 `type: simple_generator`
2. 任务启动时该 source 能被装入 alias pool
3. 生成的 alias 符合 `prefix + 随机[a-z0-9] + suffix` 规则
4. 每个生成结果都被包装为 `AliasEmailLease`
5. `CloudMailMailbox` 能无感消费该 lease
6. 相关 `unittest` 通过
7. 不影响现有 `static_list` 行为

## 后续演进方向

本次设计完成后，后续可以沿着同一路径进入真正的 phase-3：

- 将 `simple_generator` 旁边新增真实站点型 producer
- 为 service source 引入 session、cookie/token、验证邮件确认等能力
- 逐步把一次性 `load_into()` 扩展为带补货逻辑的 producer 运行模型

但这些都不属于本次范围。
