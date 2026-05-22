# Langtum 工作流测试系统 — 完整技术文档

## 系统概述

Langtum 工作流测试系统是一个 FastAPI Web 应用，用于批量将船舶设备数据提交到 Langtum AI 工作流 API，轮询获取结果，并生成 Excel 保养报告。

**技术栈：** FastAPI + SQLite (WAL) + httpx (async) + openpyxl + sse-starlette

**启动：** `cd langtum_tester && python main.py` → http://localhost:8055

---

## 项目结构

```
langtum_tester/
├── main.py              # FastAPI 入口，所有 HTTP 端点
├── config.py            # 配置常量（API Key、路径、端口）
├── db.py                # SQLite schema 和 CRUD
├── models.py            # Pydantic 模型
├── parser.py            # 解析上传的 txt 文件，匹配 Excel 元数据
├── workflow.py          # Langtum API 异步客户端（createTask / queryTask / abort）
├── runner.py            # 任务执行引擎（并发控制、轮询、结果保存）
├── excel.py             # 生成 Excel 报告（匹配客户模板）
├── static/
│   └── index.html       # 前端单页应用
├── results/             # 生成的 Excel 文件
├── uploads/             # 上传文件存储（未使用，文件内容存 DB）
└── langtum_tester.db    # SQLite 数据库
```

---

## 数据流

```
用户上传 .txt 文件
  → parser.parse_uploaded_file() 解析 JSON + 匹配 Excel 元数据
  → db.insert_file() + db.insert_task() 存入 SQLite

用户点击"开始全部"
  → runner.run_file_tasks() 用 asyncio.Semaphore 控制并发
  → 每个 task: workflow.create_task() → workflow.poll_task() → db.update_task_status()
  → SSE 推送实时更新到前端
  → 完成后自动生成 Excel

用户点击"下载结果"
  → excel.generate_file_excel() 重新生成 Excel 并返回
```

---

## 数据库 Schema

### files 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| upload_name | TEXT | 上传时的文件名（含路径前缀） |
| folder_name | TEXT | 文件夹名（文件夹上传时从 webkitRelativePath 提取） |
| ship_key | TEXT UNIQUE | 船舶唯一标识，如 `ARISTA-散货船-40008` |
| ship_name | TEXT | 船名，如 `ARISTA` |
| ship_type | TEXT | 船型，如 `散货船` |
| company | TEXT | 所属公司 |
| total_items | INTEGER | 设备总数 |
| file_content | TEXT | 上传文件原始内容 |
| parse_status | TEXT | 解析状态：success / failed |
| parse_error | TEXT | 解析错误信息 |
| status | TEXT | 文件状态：pending / running / completed |

### tasks 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| file_id | INTEGER FK | 关联 files 表，ON DELETE CASCADE |
| item_index | INTEGER | 在文件中的序号（UNIQUE per file） |
| manufacturer | TEXT | 制造商 |
| model | TEXT | 设备型号 |
| source_name | TEXT | 设备名称 |
| equip_code | TEXT | 设备编码（来自 Excel） |
| equip_group | TEXT | 设备分组（来自 Excel） |
| status | TEXT | 任务状态：pending / running / success / failed |
| wf_task_id | TEXT | Langtum 返回的 taskId |
| raw_output | TEXT | Langtum 返回的完整 detail JSON |
| error_message | TEXT | 错误信息 |
| started_at | TEXT | 开始时间 |
| completed_at | TEXT | 完成时间 |

**任务状态流转：** `pending` → `running` → `success` | `failed`

---

## API 端点

### 文件操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/files/upload` | 上传 .txt 文件（支持多文件/文件夹），解析并存入 DB |
| GET | `/api/files` | 列出所有文件，含各状态任务数 |
| GET | `/api/files/{id}/tasks` | 获取文件下所有任务 |
| POST | `/api/files/{id}/start` | 开始执行文件下所有 pending 任务，body: `{"concurrency": 20}` |
| POST | `/api/files/{id}/abort` | 中止文件下所有 running 任务 |
| DELETE | `/api/files/{id}` | 删除文件、所有任务、Excel 文件 |
| GET | `/api/files/{id}/download` | 重新生成 Excel 并下载 |
| GET | `/api/files/download-all` | 打包所有有结果的 Excel 为 ZIP 下载 |

### 任务操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/{id}/start` | 单独启动一个 pending/failed 任务 |
| POST | `/api/tasks/{id}/abort` | 中止一个 running 任务 |
| POST | `/api/tasks/{id}/retry` | 重置并重新执行一个任务 |

### SSE

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | SSE 推送，任务状态变更时推送 `task_update` 事件 |

---

## Langtum API 交互

### 创建任务

```
POST https://langtum.ship-cloud.cn/api/v1/workflow/createTask
Authorization: Bearer sk-1mwlg6bleo81
```

**请求体：**
```json
{
  "workflowEntityId": "cmpfa7efj525i7ao443aywzg6",
  "input": {
    "equipment_list": [
      {
        "manufacturer": "无锡汾锡电机有限公司",
        "model": "1FC5 356-6TA42",
        "source_name": "No.3 主发电机 No.3Generator"
      }
    ],
    "ship_type": "散货船",
    "language": ""
  }
}
```

**关键：** `equipment_list` 始终只有 1 个设备。`ship_type` 和 `language` 是必填字段，缺失会导致工作流返回空结果。

**响应：**
```json
{"status": "success", "data": {"taskId": "cmpgqxxzg..."}}
```

### 轮询结果

```
GET https://langtum.ship-cloud.cn/api/v1/workflow/queryTask/{taskId}
Authorization: Bearer sk-1mwlg6bleo81
```

**轮询策略：** 无超时限制。从 5s 间隔开始，每次 +2s，最大 15s。持续轮询直到 status 为 `SUCCEED` 或 `FAILED`。

**响应结构：**
```json
{
  "data": {
    "taskId": "cmpgqxxzg...",
    "status": "SUCCEED",
    "detail": {
      "input": {
        "equipment_list": [...],
        "ship_type": "散货船",
        "language": ""
      },
      "output": {
        "end_item": [
          {
            "source_name": "No.3 主发电机",
            "manufacturer": "无锡汾锡电机有限公司",
            "model": "1FC5 356-6TA42",
            "items": [
              {
                "maintenance_type": "关键",
                "maintenance_item": "发电机检查",
                "recommended_procedure": "...",
                "fixed_interval_value": "3",
                "fixed_interval_unit": "月",
                "runtime_threshold_value": "",
                "runtime_threshold_unit": "",
                "has_non_periodic_requirement": "false",
                "is_mandatory": "false",
                "safety_notes": "",
                "estimated_work_hours": "",
                "recommended_spares": "",
                "source_information": [
                  {"source_item_id": "82", "source_type": "历史保养记录", "file_name": "xxx.pdf", ...}
                ]
              }
            ]
          }
        ]
      },
      "startTime": "2026-05-22T09:41:14.089Z",
      "endTime": "2026-05-22T09:41:20.916Z"
    },
    "runtimeState": {...}
  }
}
```

### 中止任务

```
POST https://langtum.ship-cloud.cn/api/v1/workflow/abort
Authorization: Bearer sk-1mwlg6bleo81
Body: {"taskId": "cmpgqxxzg..."}
```

---

## 文件解析流程

### 输入文件格式

上传的 `.txt` 文件包含非标准 JSON（key 无引号）：
```
[
  {manufacturer:"MAN", model:"6S60MC", source_name:"主机"},
  {manufacturer:"ABB", model:"AMG500", source_name:"发电机"},
  ...
]
```

### 解析步骤

1. **正则修复**：`re.sub(r'^(\s*)(\w+)(:)', r'\1"\2":', content)` 给 key 加引号
2. **json.loads** 解析为列表
3. **文件名提取 ship_key**：`ARISTA-散货船-40008_设备信息数组.txt` → `ARISTA-散货船-40008`（先去掉文件夹前缀）
4. **匹配 Excel**：将 ship_key 归一化后与 `20艘船舶设备列表.xlsx` 的 sheet 名匹配，获取 ship_name / ship_type / company 和 equip_code / equip_group
5. **逐项入库**：每个设备一条 task 记录

---

## Excel 生成

### 列映射（25 列）

| 列号 | 表头 | 数据来源 |
|------|------|----------|
| 1-6 | 船名/船型/船籍国/船级社/IMO编号/所属公司 | files 表 |
| 7 | 设备编码 | tasks.equip_code |
| 8-10 | 设备名称/设备型号/制造商 | end_item（优先）或 tasks 表 |
| 11 | 保养类型 | item.maintenance_type |
| 12 | 保养项目 | item.maintenance_item |
| 13 | 保养步骤 | item.recommended_procedure |
| 14-15 | 固定周期数值/单位 | item.fixed_interval_value / fixed_interval_unit |
| 16-17 | 运行时长数值/单位 | item.runtime_threshold_value / runtime_threshold_unit |
| 18 | 是否不定期 | item.has_non_periodic_requirement |
| 19 | 是否必须 | item.is_mandatory |
| 20 | 安全注意事项 | item.safety_notes |
| 21 | 预计工时 | item.estimated_work_hours |
| 22 | 所需备件 | item.recommended_spares |
| 23 | 参考依据 | item.source_information（JSON 数组序列化为字符串） |
| 24 | 参考设备说明书 | source_information 中所有 file_name 去重后合并 |
| 25 | 参考政策文件 | 空 |

### raw_output → Excel 的解析路径

```
raw_output (DB) = json.dumps(result["detail"])
  → detail 结构: {"input": {...}, "output": {"end_item": [...]}, ...}
  → extract_end_items() 取 detail["output"]["end_item"] 或 detail["end_item"]
  → 每个 end_item 可包含多个 maintenance item
  → 每个 maintenance item 生成一行 Excel
```

---

## 前端架构

### 布局

- **顶部栏**：标题、批量下载、上传按钮、并发数输入
- **左侧面板**：文件列表，按 folder_name 分组显示
- **右侧面板**：选中文件的设备任务表格

### 实时更新

- SSE 连接 `/api/events`，收到 `task_update` 事件后自动刷新文件列表和任务列表
- 每次操作后调用 `fullRefresh()` 手动刷新
- 运行中任务通过 `scheduleRefresh()` 2 秒后自动刷新

### 任务详情展开

点击任务行展开详情区域，显示三部分：
1. **输入参数**：DB 中的 manufacturer/model/source_name
2. **实际请求参数**：raw_output 中保存的 Langtum input（含 equipment_list、ship_type、language）
3. **输出结果**：解析 end_item 展示保养项，或错误信息

---

## 关键设计决策

| 决策 | 原因 |
|------|------|
| SQLite WAL 模式 | 支持异步并发读写 |
| SSE 而非 WebSocket | 单向推送足够，实现简单 |
| 每次下载重新生成 Excel | 确保下载最新结果 |
| equipment_list 只含 1 项 | 每个设备独立调用工作流 |
| ship_type 必须传入 | 缺失 ship_type 工作流会返回空结果 |
| 无 polling 超时 | 部分设备需要较长时间处理（3 分钟以上） |
| 文件名去除路径前缀 | 文件夹上传时 upload_name 含路径前缀，ship_key 需纯净匹配 |
