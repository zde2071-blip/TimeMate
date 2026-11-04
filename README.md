# TimeMate 线上版

把邮件中的信息、待办、日程和截止事项清晰地整理在一起。本分支保留原有完整网站功能，供自行部署与后续维护。

**希望在自己电脑上直接使用，请前往[本地版](https://github.com/zde2071-blip/TimeMate/tree/local)。** 当前仓库公开的是源码，线上托管服务是否恢复另行维护。

## 功能

- 多用户登录，账号之间的邮件、配置和事项相互隔离。
- 多邮箱接入、邮件摘要与分类、原文查看和中文翻译。
- 日程与截止事项的核对、编辑、完成及日历订阅。
- AI 对话、信息接入关系图，以及个人 Agent 连接。

## 自行部署

按照[多人版部署说明](docs/多人版说明.md)配置持久化数据目录、独立加密密钥、注册验证邮件和 HTTPS。使用自己的邮箱与模型服务配置，不需要也不应使用项目维护者的密钥。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/cloud.txt
.venv/bin/python -m tools.preview
```

上述命令只用于本机预览多人版，注册验证码仍需配置发信服务；免注册的单人使用请选本地版。生产启动入口是 `python -m backend.cloud serve`，具体环境变量见部署说明。

公开代码不会恢复旧服务器数据。用户邮件、授权码、模型 Key、服务器数据与加密密钥需要独立保存和备份。模型分析会把相关邮件内容发送给用户配置的模型服务。

## 开发与反馈

- [代码结构与开发说明](docs/development.md)
- [个人 Agent 接入说明](docs/personal-agents.md)
- [问题与建议](https://github.com/zde2071-blip/TimeMate/issues)（请勿贴出真实邮件与凭证）

## 许可证

TimeMate 项目代码使用 [GNU AGPL-3.0-only](LICENSE)。第三方依赖与素材保留各自许可。
