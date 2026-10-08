# 邮件助手

把学校 Outlook 邮件自动转发到自己的 QQ 邮箱后，邮件助手读取邮件，并通过用户配置的模型 API 分析分类、简略标题、摘要和待办。用户核对后，可以把事项加入日程或截止事项。

当前 `feature/multiuser` 分支是支持多人登录的网站版本，每位用户连接自己的邮箱和模型服务，邮件、设置和事项按账号隔离。`main` 保留较早的单人版本。

## 仓库怎么读

目录按职责划分，而不是把所有同一种后缀的文件放在一起：

```text
backend/                 后端程序
  cloud.py               登录、账号隔离、网页接口和多人运行入口
  app.py                 每位用户的收信、分析和事项操作
  mail/                  邮件相关功能
    ingest.py            连接邮箱、读取和导入邮件
    analysis.py          分析提示词、结果校验和事项提取
    titles.py            简略标题的读取与校验
    dates.py             邮件日期处理
    original.py          原邮件解析和安全展示
    translation.py       原邮件翻译
  events/                日程与截止事项
    event_join.py        事项加入、重复合并和更新核对
  core/                  多个功能共用的基础能力
    ai_services.py       模型服务调用
    database.py          邮件数据库与版本升级
    operation_status.py  操作进度和结果状态
    user_errors.py       错误类型和用户提示
  migrations/            旧数据转换
    legacy_titles.py     旧版标题的兼容转换
web/                     浏览器页面
  index.html             主界面内容和结构
  login.html             登录与注册页面
  styles.css             主界面样式
  main.js                主界面交互行为
tools/                   本机开发辅助工具
requirements/            公共库与网站服务的依赖清单
tests/                   自动验证功能的测试
docs/                    使用与部署说明
```

程序直接从目录里的模块启动，不再保留根目录的三个启动文件。根目录只保留 `README.md`、`Dockerfile`、`.gitignore` 和 `.dockerignore`：它们分别供 GitHub 展示说明、部署构建、Git 忽略文件和 Docker 忽略文件使用。

如果想逐步理解这个项目，建议按一次操作走过的路径阅读：

1. `web/index.html` 和 `web/main.js`：页面提供什么操作，点击后向后端请求什么。
2. `backend/cloud.py`：请求如何检查登录状态、找到当前用户，并调用功能。
3. `backend/app.py`：收信、分析与事项操作如何串起来。
4. `backend/mail/ingest.py` 和 `backend/mail/analysis.py`：邮件如何进入系统，再变成分析结果。
5. `backend/core/ai_services.py` 和 `backend/core/database.py`：模型如何调用，结果如何保存。
6. `backend/events/event_join.py`：用户确认事项后，如何加入和合并。

文件夹用来归类，文件用来拆分职责。一个功能可以调用其他目录的公共能力，不必把所有代码复制进同一个文件。

## 本机预览多人版

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements/cloud.txt
.venv/bin/python -m tools.preview
```

预览工具只监听本机，并在被 Git 忽略的 `cloud-data/development.secret` 中保存开发密钥。邮箱验证码注册、账号恢复、正式运行、日历订阅和 Railway 部署步骤见 [多人版说明](docs/多人版说明.md)。

生产环境通过 `python -m backend.cloud serve` 启动。仓库中的 Docker 配置已同步更新。下面的命令均在仓库根目录运行。

## 数据存在哪里

GitHub 保存程序和说明，不保存用户邮件、密码、QQ 授权码或 API Key。

多人版运行数据默认在 `cloud-data/`，部署时使用配置的持久化数据目录。每位用户的邮件和设置保存在该目录下各自的数据空间。多人版凭证使用服务器密钥加密；密钥与运行数据需要另外备份，不能依靠 GitHub 恢复。

## 验证修改

```sh
.venv/bin/python -m unittest discover -s tests
for test in tests/test_*.js; do node "$test"; done
```

修改代码后先验证，再提交和推送 GitHub。线上网站在部署完成后才更新。
