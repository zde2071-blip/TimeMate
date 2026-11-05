# TimeMate 本地版

在自己的电脑上读取邮件、核对摘要与待办，管理日程和截止事项。

本分支只开放「邮件处理」「重要事项」两个工作区，保留邮箱、AI 服务和日历设置。AI 对话、信息接入、个人 Agent 和网站账号功能不在本地版开放。

## 分支与开发

- `local`：当前本地开发和单人使用分支，提供邮件处理、重要事项及相关设置。
- [`main`](https://github.com/zde2071-blip/TimeMate)：保留完整稳定的多人版，接收本地验证后的共用改动。

不再维护单独的 `online` 分支。先在 `local` 完善功能，测试后将共用改动合回 `main`，保留多人登录与数据隔离。合并代码与恢复线上部署分别安排；当前本地启动入口尚未合入 `main`。

## 启动

支持 macOS、Linux；Windows 请先使用 WSL。目前提供源码版，尚未打包成独立安装应用。

先安装 Python 3.12 或更高版本，[下载本地版源码 ZIP](https://github.com/zde2071-blip/TimeMate/archive/refs/heads/local.zip) 并解压。在终端进入此目录：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/cloud.txt
.venv/bin/python -m backend.local
```

macOS 也可以双击 `start.command`：第一次会建立独立 Python 环境、下载依赖，之后直接启动。浏览器会打开 http://127.0.0.1:18744 。关闭运行程序的终端或按 Ctrl+C 停止；再次启动继续使用原数据。

本地版只监听本机地址，不作为局域网或公网服务器使用。不要用 `backend.cloud serve` 启动本地版；那是原多人版入口。仓库中的 Dockerfile 仍是线上部署配置，本地版暂不提供 Docker 启动方案。

## 第一次使用

1. 打开左下角「设置」，添加邮箱。无法直接接入的邮箱沿用原有转发流程：先连接接收邮箱，再设置源邮箱自动转发。
2. 添加自己的 AI 服务 API Key，用于邮件摘要、分类、事项识别和翻译。
3. 在「邮件处理」开启检查，核对结果后加入事项；在「重要事项」查看、编辑或完成。

本地运行不等于离线运行：收信仍需访问邮箱服务；分析和翻译会将相关邮件内容发送给你选择的模型服务，费用由该服务商收取。

## 数据与备份

默认数据目录：`~/.timemate/`。邮件、事项和配置保存在本机，凭证由该目录中的 `local.secret` 加密。备份时先停止程序，再复制整个目录；恢复时也要同时保留密钥。不要把这个目录、IMAP 授权码或 API Key 上传 GitHub。

可以指定数据目录和端口：

```sh
.venv/bin/python -m backend.local --data-dir /你的备份目录 --port 18745
```

电脑关机、休眠或程序停止时不会自动检查邮件。原线上用户的数据在服务器持久化存储里，不在 GitHub；本地版不会自动取得旧线上数据，请先保留服务器备份。

日历订阅链接只在这台电脑可达，远端日历服务无法访问 `127.0.0.1`。若需要跨设备同步，需另行提供可达的服务，不能把本地订阅当作已实现的跨设备同步。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests
for test in tests/test_*.js; do node "$test"; done
```

## 许可

TimeMate 项目代码使用 GNU AGPL-3.0-only，见 [LICENSE](LICENSE)。第三方依赖与素材保留各自许可。

允许使用、修改和商用；分发修改版或以修改版提供网络服务时，须按 AGPL 要求提供对应源码并保留相关声明。仓库公开不代表可以任意去掉许可。

## 反馈与开发

问题与建议请提交 [Issue](https://github.com/zde2071-blip/TimeMate/issues)，截图请遮住邮件内容和凭证。代码结构见 [开发说明](docs/development.md)；其中多人账号、AI 对话和 Agent 部分仅适用于完整网站版。
