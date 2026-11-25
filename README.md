# TikTok Copy Analyzer

本地中文工作台，用于分析英文口播、人工审核组件，以及将审核版本写入飞书多维表格。应用仅监听本机，默认离线运行。数据和写入进度保存在项目的 `data/workspace.sqlite3`。

## 启动

**Windows PowerShell**：在项目目录执行以下命令，然后打开 http://127.0.0.1:8765 。保持终端开启，按 Ctrl+C 停止。

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

启动器优先寻找项目虚拟环境、本机 Codex 附带的 Python 和系统 Python。环境缺少 Pydantic 时会在项目内创建虚拟环境并安装依赖。端口被占用时可以在命令末尾添加 `-Port 8766`。同一数据目录请只启动一个应用实例。

**手动安装**：推荐 Python 3.12。Windows 也可在项目目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

macOS / Linux 使用 `python3.12 -m venv .venv`，然后用 `.venv/bin/python` 执行上述 pip 和 app.py 命令。

## 先走一遍离线流程

1. 打开「文案工作台」，点击「填入示例」后「开始分析」。钥匙扣示例内置完整中文分析。其他文案在 Mock 分析模式下使用分句和显式占位内容，供测试审核流程。
2. 在报告中查看整篇分析、逐句拆解、英文表达资产和说服逻辑。可编辑中文释义、句式、语块、标签、适用场景和边界，原始英文只读。
3. 在「逐句拆解」逐项通过或驳回。也可以先「全部通过」，再单独驳回某句。
4. 点击「保存审核结果」，核对「写入清单」。原稿记录保留完整输入与已审核的整体报告。组件按原句顺序入库；只有**全部来源句都通过**的资产进入清单。全部驳回时可保存审核，不产生写入。
5. 点击「确认并模拟写入」并确认，即可看到本地模拟 Record ID。真实模式的按钮为「确认并写入飞书」。首次确认会锁定该审核版本。
6. 从「分析历史」重新打开草稿或查看日志。写入中断后，在原记录的清单中点击「重试已确认的写入」。应用重启后也可继续。

## 连接真实服务

把 `.env.example` 复制为同目录的 `.env`，填写后重启。已有系统环境变量优先。同名文件只复制一次，以免覆盖配置。

```powershell
Copy-Item .env.example .env
```

| 配置 | 作用与获取方式 |
| --- | --- |
| ANALYSIS_MODE | `mock` 离线演示，`live` 调用模型 |
| LLM_API_KEY | 在模型服务商的开发者控制台创建服务端 API Key |
| LLM_BASE_URL | 服务商给出的兼容 Chat Completions 服务根地址，通常含 `/v1` |
| LLM_MODEL | 账号已开通且支持严格 JSON Schema 输出的模型 ID |
| STORAGE_MODE | `mock` 写本地模拟库，`live` 写飞书 |
| FEISHU_APP_ID | 企业自建应用「凭证与基础信息」中的 App ID |
| FEISHU_APP_SECRET | 同页的 App Secret |
| FEISHU_APP_TOKEN | 目标多维表格链接中 `/base/` 之后、查询参数之前的标识；与 App ID、table_id 是不同值 |

使用 OpenAI 时可在 [API Keys](https://platform.openai.com/api-keys) 创建密钥，并在 [模型目录](https://developers.openai.com/api/docs/models) 核对账号可用的模型。真实分析会将输入文案及选填背景发给配置的模型。视频链接仅作为来源保存。

在 [飞书开发者后台](https://open.feishu.cn/app) 创建企业自建应用，申请多维表格读写管理权限（如 `bitable:app`），发布应用版本并完成租户审批。在飞书内新建或选择目标多维表格，通过文档应用入口为该应用授予可管理权限。若只拿到知识库 `/wiki/` 链接，请获取底层多维表格的 `obj_token`。首次人工确认时系统自动建表、补字段并写入记录。可直接使用一个空白 Base，无需手工复制三张表。具体权限和文档访问步骤见[飞书多维表格接入指南](https://open.feishu.cn/document/introduction-2?lang=zh-CN)及[多维表格常见问题](https://open.feishu.cn/document/docs/bitable-v1/faq?lang=zh-CN)。

可先将分析设为 live、写入保持 mock，以真实口播检查模型质量。准备入库时将两项设为 live，重启并重新提交原文，生成绑定真实目标的审核记录。历史任务保留创建时的分析模式和写入目标。

## 数据关系与重复检测

| 表 | 内容与来源 |
| --- | --- |
| Scripts | UID、不可改写的全文、视频来源、产品信息、九项整篇分析、通过句子的推进逻辑和审核状态 |
| Copy Components | UID、Script 双向关联、原文序号和英文、中文释义、角色、分类、句式、语块、逐句报告、审核状态及 Patterns 双向关联 |
| Expression Patterns | UID、L1/L2/L3、英文模板、通用或产品专属、场景、限制、标签及状态。通过反向组件关联追溯原稿与视频 |

同一输入、背景、运行模式和目标 Base 的重复提交会重新打开原记录。表达按层级、复用范围及规范化模板生成确定性 UID，产品专属表达还区分产品。匹配时统一大小写、兼容字符、空白和结尾标点。已有资产优先保留原记录，新组件追加来源关联。语义近似但写法不同的模板可在审核阶段统一措辞。

写入前持久化每项的 UUIDv4 幂等令牌。飞书按 UID 查找记录后创建或关联，将实际返回的 Record ID 和每次处理的日志存入 SQLite。中断恢复时重用已有回执及令牌，保留原审核快照。同名字段与预期类型冲突时，界面显示错误，请核对后重试。参考[飞书新增记录接口](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create)。

## 工程与测试

- `engine.py` 定义唯一的 Pydantic 报告模型，自动产生模型接口使用的 JSON Schema。启动后访问 `/api/schema` 可查看。返回结果和人工修改都经过字段、原句、来源范围校验。
- `workflow.py` 管理原文、审核版本、SQLite 事务、清单、日志和断点恢复。
- `feishu.py` 处理租户令牌、字段与双向关联、UID 搜索及幂等创建。
- `app.py` 与 `static/` 提供本地 HTTP 接口及原生 Web 页面。
- 测试使用临时数据库与模拟远端响应，涵盖模型契约、飞书接口契约和 HTTP 端到端流程。使用运行应用的同一 Python 执行：

```powershell
python -m unittest discover -v
```

真实模型和真实飞书租户的验收需自行配置凭证。备份时先停止应用，再复制整个 `data/` 目录。密钥、本地数据库和虚拟环境均已加入 Git 忽略规则。

