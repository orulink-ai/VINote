---
title: 本地与树莓派部署
description: 本地开发、Docker 运行以及树莓派部署方式说明。
---

# 本地与树莓派部署

## 本地开发

后端：

```bash
uvicorn main:app --host 0.0.0.0 --port 8900 --reload
```

前端：

```bash
cd frontend
npm run web:dev
```

文档站：

```bash
cd docs
npm run docs:dev
```

## 默认端口

- 后端 API / Swagger：`8900`
- 前端应用：`3100`
- 文档站：`3101`

## 本地 Docker 运行

```bash
docker compose up --build
```

默认会启动：

- `postgres`
- `backend`
- `frontend`
- `docs`

## 树莓派部署

VINote 现在支持两条树莓派部署路径：

- 开发机手动部署
- GitHub Actions 驱动的树莓派自托管 Runner 自动部署

### 手动部署

推荐顺序：

1. 从 `.env.example` 生成根目录 `.env`
2. 从 `deploy/pi/local.env.example` 生成 `deploy/pi/local.env`
3. 先运行 bootstrap，准备 Docker、Docker Compose 和远程应用目录
4. 再运行 deploy

Bootstrap：

```powershell
.\deploy\pi\bootstrap-pi.ps1
```

```bash
./deploy/pi/bootstrap-pi.sh
```

Deploy：

```powershell
.\deploy\pi\deploy-pi-interactive.ps1
```

```bash
./deploy/pi/deploy-pi-interactive.sh
```

```powershell
.\deploy\pi\deploy-pi.ps1
```

```bash
./deploy/pi/deploy-pi.sh
```

手动脚本仍然保留，作为紧急重部署和调试的 fallback。

### `dev` 自动部署

推荐的共享测试环境流程是：

- PR 合并到 `dev`
- GitHub Actions 收到 `push`
- 树莓派 self-hosted runner 拉取合并后的 commit
- 树莓派本机重新构建并启动服务

关键配置：

- Workflow：`.github/workflows/deploy-pi-dev.yml`
- 触发条件：`push` 到 `dev`，以及 `workflow_dispatch`
- Runner 标签：`self-hosted`、`linux`、`arm`、`pi`、`vinote-test`
- GitHub Environment：`pi-test`
- Runner 本机部署脚本：`deploy/pi/deploy-from-checkout.sh`

### 树莓派一次性准备

在树莓派上完成以下初始化：

1. 安装 Docker 和 Docker Compose
2. 在独立目录中安装 GitHub Actions runner，例如 `/home/zouyu/actions-runner`
3. 注册 runner，并打上 `self-hosted,linux,arm,pi,vinote-test` 标签
4. 将 runner 安装为系统服务
5. 将 runner 用户加入 `docker` 组
6. 保持应用部署目录为 `/home/zouyu/vinote`

不要把应用目录直接拿来当 runner 的工作目录。

### 逐步操作清单

在树莓派上按这个顺序操作：

1. 使用最终要运行 runner 和应用的那个账号登录树莓派。
2. 如果还没装，先安装 Docker 和 Docker Compose。
3. 创建应用目录和持久化目录：

```bash
mkdir -p /home/zouyu/vinote/data /home/zouyu/vinote/output
```

4. 创建独立的 runner 工作目录：

```bash
mkdir -p /home/zouyu/actions-runner
cd /home/zouyu/actions-runner
```

5. 打开 GitHub 仓库，进入：
   `Settings -> Actions -> Runners -> New self-hosted runner`
6. 选择 Linux 和 ARM，复制 GitHub 给你的下载与配置命令。
7. 在树莓派上执行这些命令，并把 labels 设置为：
   `self-hosted,linux,arm,pi,vinote-test`
8. 把 runner 安装为系统服务并启动：

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

9. 把 runner 用户加入 `docker` 组：

```bash
sudo usermod -aG docker zouyu
```

10. 修改组之后重启 runner 服务：

```bash
sudo ./svc.sh stop
sudo ./svc.sh start
```

可以在树莓派上这样快速检查：

```bash
docker --version
docker compose version || docker-compose version
id -nG
sudo ./svc.sh status
```

### GitHub Environment `pi-test`

在 GitHub 中配置：

- Secret `PI_TEST_ENV_FILE`
  - 内容为树莓派测试环境使用的完整根目录 `.env`
- Variable `PI_REMOTE_DIR`
  - 默认值：`/home/zouyu/vinote`
- Variable `FRONTEND_PORT`
  - 默认值：`3100`
- Variable `BACKEND_PORT`
  - 默认值：`8900`
- Variable `DOCS_PORT`
  - 默认值：`3101`

GitHub 侧操作清单：

1. 打开仓库的 `Settings -> Environments`。
2. 创建名为 `pi-test` 的 Environment。
3. 新增 secret `PI_TEST_ENV_FILE`，值为树莓派测试环境使用的完整 `.env` 内容。
4. 新增 variables：
   `PI_REMOTE_DIR=/home/zouyu/vinote`
   `FRONTEND_PORT=3100`
   `BACKEND_PORT=8900`
   `DOCS_PORT=3101`
5. 如果你希望 `dev` 合并后立即自动部署，就不要开启 reviewer gate。
6. 到 `Actions` 页面确认能看到 `Deploy Pi Test Environment` 这个 workflow。

### 自动部署行为

workflow 会：

1. 在树莓派 runner 上 checkout 当前触发 commit
2. 从 `PI_TEST_ENV_FILE` 写入 `.env`
3. 检查 Docker、Docker Compose、`curl` 以及 docker 组权限
4. 调用 `deploy/pi/deploy-from-checkout.sh`
5. 以 `docker compose up -d --build --remove-orphans` 重建并拉起服务
6. 对 `127.0.0.1` 上的 backend、frontend、docs 做 smoke check
7. 输出 `docker compose ps`
8. 失败时输出 backend / frontend / docs 日志

`deploy-from-checkout.sh` 会刷新应用目录，但会保留：

- `data/`
- `output/`

### 手动触发部署到底怎么操作

如果你不希望 `dev` 每次合并后都立即影响局域网共享环境，更稳的方式是只保留 `workflow_dispatch`，然后在你确认本地自测和 CI 都通过之后，再手动点一次部署。

这里的“手动触发”不是让你再去本地执行命令，而是在 GitHub 页面里操作：

1. 打开仓库
2. 进入 `Actions`
3. 选择 `Deploy Pi Test Environment`
4. 点击右上角 `Run workflow`
5. 选择要部署的分支，一般是 `dev`
6. 确认运行

然后 GitHub 会把任务派发给树莓派上的 self-hosted runner，由树莓派本机完成部署。正常情况下，你不需要再 SSH 到树莓派手动执行部署命令。

如果以后你给 Environment 增加 reviewer gate，那么部署会在开始前等待审批；如果没有配置审批，手动触发就是一个 GitHub 页面上的按钮。

### 数据保留与注意事项

按当前部署设计，正常部署后，原有团队成员的数据、笔记数据和已生成产物应该都会保留。

原因是：

- `docker-compose.yml` 里的 Postgres 使用命名 volume
- `deploy-from-checkout.sh` 会刷新代码目录，但会保留 `data/` 和 `output/`
- workflow 使用的是 `docker compose up -d --build --remove-orphans`
- 当前流程不会执行 `docker compose down -v`

正常情况下会保留的内容：

- 数据库中的用户、团队、笔记、设置
- `/home/zouyu/vinote/data` 里的已有文件
- `/home/zouyu/vinote/output` 里的已有文件

以下情况仍然可能导致数据丢失或部署到错误位置：

- 手动执行了 `docker compose down -v`
- 手动删除了 Docker volume
- 手动删除了 `/home/zouyu/vinote/data` 或 `/home/zouyu/vinote/output`
- 错误修改了 `PI_REMOTE_DIR`
- 改动了 `COMPOSE_PROJECT_NAME`，导致 Compose 指向了另一套项目
- 引入了破坏性数据库迁移

对局域网共享环境的推荐做法：

- 先在本机自测
- 等 PR CI 跑完
- 确认无误后再手动触发树莓派部署
- 把 `docker compose down -v` 视为破坏性恢复命令，不要作为日常部署命令使用

## 局域网说明

- 当 `SHARE_BASE_URL` 为空时，后端会尽量自动推断局域网分享地址
- 如果前端需要跳转到独立部署的文档站，请设置 `VITE_DOCS_BASE_URL`
- 开启自动部署后，手动脚本依然是运维 fallback
- 更多树莓派运维说明见 `deploy/pi/README.md`
