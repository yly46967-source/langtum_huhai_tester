# Langtum 工作流连接与测试指南

> 生成时间：2026/04/22

---

## 一、所需信息

| 信息项 | 说明 | 示例 |
|-------|------|------|
| **BASE_URL** | Langtum 平台域名 | `https://demo.langcore.cn` |
| **API_KEY** | Bearer 认证令牌 | `sk-kirxlxifznqm` |
| **WORKFLOW_ID** | 工作流实体 ID | `cmo8txbc40adlecrubzq4s5bj` |
| **输入参数** | 工作流定义的输入变量 | `qq: [{id, kind, content}]` |

### 信息获取方式

- **BASE_URL**: Langtum 平台提供方给出
- **API_KEY**: 控制台 → 设置 → API Keys
- **WORKFLOW_ID**: 工作流详情页 URL 中提取
  ```
  https://demo.langcore.cn/workflow/detail/cmxxxxx
                                        └────────┘
                                  WORKFLOW_ID
  ```
- **输入参数**: 工作流编辑页面 → 输入变量定义

---

## 二、快速测试步骤

### Step 1：测试 API 连通性

```bash
curl -X POST "{BASE_URL}/api/v1/workflow/createTask" \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"workflowEntityId":"{WORKFLOW_ID}","input":{}}'
```

**预期返回：**
```json
{"status":"success","data":{"taskId":"cmo9xxxxx"}}
```

**如果返回 401：** API_KEY 错误或平台不匹配
**如果返回 404：** WORKFLOW_ID 不存在

---

### Step 2：查询任务结果

```bash
curl "{BASE_URL}/api/v1/workflow/queryTask/{taskId}" \
  -H "Authorization: Bearer {API_KEY}"
```

**返回示例：**
```json
{
  "status": "success",
  "data": {
    "taskId": "cmo9xxxxx",
    "status": "SUCCEED",
    "detail": {
      "input": {...},
      "output": {...},
      "startTime": "2026-04-22T01:46:58.481Z",
      "endTime": "2026-04-22T01:46:58.550Z"
    }
  }
}
```

**状态值：**
- `SUCCEED` — 执行成功
- `FAILED` — 执行失败
- `RUNNING` — 执行中

---

### Step 3：测试流式输出

```bash
curl -N "{BASE_URL}/api/v1/log/workflow/{taskId}/stream" \
  -H "Authorization: Bearer {API_KEY}"
```

**输出格式（SSE）：**
```
data: {"type":"workflow-runtime",...}
data: {"type":"workflow-finished",...}
```

---

## 三、输入参数调试方法

### 逐步调试法

当不确定参数格式时，从空输入开始，根据错误逐步修正：

```
1. 空输入测试       → 查看需要哪些参数
2. 添加参数名称     → 调整参数类型
3. 修正参数格式     → 调整对象结构
4. 填充参数值       → 验证枚举值
```

### 调试示例

| 尝试 | 输入 | 错误信息 | 修正 |
|------|------|---------|------|
| 1 | `{}` | `missingProperty: qq` | 添加 qq 参数 |
| 2 | `{"qq": "text"}` | `must be array` | 改为数组 |
| 3 | `{"qq": ["str"]}` | `must be object` | 改为对象 |
| 4 | `{"qq": [{}]}` | `missingProperty: id` | 添加 id |
| 5 | `{"qq": [{id:"x"}]}` | `missingProperty: kind` | 添加 kind |
| 6 | `{"qq": [{id:"x",kind:"file"}]}` | `enum values: [...]` | 使用正确的枚举值 |
| 7 | `{"qq": [{id:"x",kind:"TEXT"}]}` | ✅ **成功** | |

### 错误类型对照表

| 错误类型 | JSON Schema 关键词 | 修正方法 |
|---------|-------------------|---------|
| 缺少必填字段 | `missingProperty` | 添加该字段 |
| 类型错误 | `type` | 按要求修改类型 |
| 枚举值错误 | `enum` | 使用允许的值之一 |
| 格式错误 | `format` | 检查字符串格式 |

---

## 四、文件类型参数格式

### 文件对象结构

```json
{
  "qq": [
    {
      "id": "文件唯一标识",
      "kind": "文件类型枚举",
      "content": "文件内容"
    }
  ]
}
```

### kind 枚举值

| 枚举值 | 说明 |
|--------|------|
| `TEXT` | 纯文本 |
| `PDF` | PDF 文档 |
| `DOCX` | Word 文档 (.docx) |
| `DOC` | Word 文档 (.doc) |
| `EXCEL` | Excel 表格 |
| `CSV` | CSV 文件 |
| `PPT` | PowerPoint 演示文稿 |
| `AUDIO` | 音频文件 |
| `VIDEO` | 视频文件 |
| `IMG` | 图片文件 |

---

## 五、完整测试脚本

### Bash 脚本 (Linux/Mac/WSL)

```bash
#!/bin/bash

# 配置
BASE_URL="https://demo.langcore.cn"
API_KEY="sk-kirxlxifznqm"
WORKFLOW_ID="cmo8txbc40adlecrubzq4s5bj"

# 1. 创建任务
echo "=== Step 1: 创建任务 ==="
RESP=$(curl -s -X POST "${BASE_URL}/api/v1/workflow/createTask" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"workflowEntityId\": \"${WORKFLOW_ID}\",
    \"input\": {
      \"qq\": [{
        \"id\": \"test-file-001\",
        \"kind\": \"TEXT\",
        \"content\": \"测试内容\"
      }]
    }
  }")

echo "$RESP" | head -c 200

TASK_ID=$(echo "$RESP" | grep -o '"taskId":"[^"]*"' | cut -d'"' -f4)
echo -e "\n\nTask ID: $TASK_ID"

# 2. 等待并查询结果
echo -e "\n=== Step 2: 查询结果 ==="
sleep 2
curl -s "${BASE_URL}/api/v1/workflow/queryTask/${TASK_ID}" \
  -H "Authorization: Bearer ${API_KEY}" | head -c 300

# 3. 流式输出
echo -e "\n\n=== Step 3: 流式输出 ==="
curl -s -N "${BASE_URL}/api/v1/log/workflow/${TASK_ID}/stream" \
  -H "Authorization: Bearer ${API_KEY}" --max-time 3
```

### PowerShell 脚本 (Windows)

```powershell
# 配置
$BaseUrl = "https://demo.langcore.cn"
$ApiKey = "sk-kirxlxifznqm"
$WorkflowId = "cmo8txbc40adlecrubzq4s5bj"

# 1. 创建任务
Write-Host "=== Step 1: 创建任务 ===" -ForegroundColor Cyan
$Body = @{
    workflowEntityId = $WorkflowId
    input = @{
        qq = @(
            @{
                id = "test-file-001"
                kind = "TEXT"
                content = "测试内容"
            }
        )
    }
} | ConvertTo-Json -Depth 10

$Response = Invoke-RestMethod -Uri "$BaseUrl/api/v1/workflow/createTask" `
    -Method POST -Headers @{"Authorization"="Bearer $ApiKey"} `
    -ContentType "application/json" -Body $Body

$TaskId = $Response.data.taskId
Write-Host "Task ID: $TaskId" -ForegroundColor Green

# 2. 查询结果
Write-Host "`n=== Step 2: 查询结果 ===" -ForegroundColor Cyan
Start-Sleep -Seconds 2
$Result = Invoke-RestMethod -Uri "$BaseUrl/api/v1/workflow/queryTask/$TaskId" `
    -Headers @{"Authorization"="Bearer $ApiKey"}
$Result | ConvertTo-Json -Depth 10

# 3. 流式输出
Write-Host "`n=== Step 3: 流式输出 ===" -ForegroundColor Cyan
curl.exe -N "$BaseUrl/api/v1/log/workflow/$TaskId/stream" `
    -H "Authorization: Bearer $ApiKey" --max-time 3
```

---

## 六、API 端点汇总

| 端点 | 方法 | 路径 | 用途 |
|------|------|------|------|
| **createTask** | POST | `/api/v1/workflow/createTask` | 创建工作流任务 |
| **queryTask** | GET | `/api/v1/workflow/queryTask/{taskId}` | 查询任务状态和结果 |
| **stream** | GET | `/api/v1/log/workflow/{taskId}/stream` | 订阅实时执行日志（SSE） |

---

## 七、常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| **401 Unauthorized** | API_KEY 错误或平台不匹配 | 确认 KEY 是否对应正确的 BASE_URL |
| **404 Not Found** | WORKFLOW_ID 不存在 | 从工作流详情页重新复制 ID |
| **500 Internal Error** | 参数格式错误 | 查看返回的 detail.output.error 详情 |
| **任务执行失败** | 输入参数不符合业务逻辑 | 检查参数值是否符合业务要求 |
| **任务超时** | 执行时间过长或卡死 | 检查工作流逻辑，确认资源充足 |

---

## 八、测试清单

接入新工作流时，按以下清单逐项验证：

- [ ] 获取 BASE_URL、API_KEY、WORKFLOW_ID
- [ ] 确认输入参数名称和类型
- [ ] 确认输出字段格式
- [ ] 测试空输入，查看错误提示
- [ ] 逐步修正参数格式直到成功
- [ ] 验证输出结果符合预期
- [ ] 测试流式输出是否正常
- [ ] 记录完整的请求和响应格式

---

## 九、测试记录模板

```
工作流名称: ___________
测试日期: ___________

配置信息:
- BASE_URL: ___________
- API_KEY: ___________
- WORKFLOW_ID: ___________

输入参数:
- 参数名: ___________
- 参数类型: ___________
- 示例值: ___________

输出格式:
- 字段1: ___________
- 字段2: ___________

测试结果:
- 连接状态: [ ] 通过 [ ] 失败
- 执行状态: [ ] SUCCEED [ ] FAILED
- 返回数据: ___________
```
