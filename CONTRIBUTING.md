# 贡献指南

感谢你对 KB-Copilot 的关注。欢迎通过 Issue 与 Pull Request 参与改进。

## 开发环境

- **后端**：[uv](https://docs.astral.sh/uv/)，Python 3.11+，MySQL；详见根目录 [README.md](README.md) 与 [backend/README.md](backend/README.md)。
- **前端**：Node.js（建议 LTS），在 `frontend/` 下执行 `npm install` 与 `npm run dev`。

本地提交前建议：

- 后端：在 `backend/` 执行 `uv run python -c "from app.main import app"`，确认应用可导入。
- 前端：在 `frontend/` 执行 `npm run build`，确认生产构建通过。

## 变更记录与发版

约定式提交（如 `feat:`、`fix:`、`docs:`）推送到 `main` 后，工作流 **Release Please** 可自动汇总并打开更新 [CHANGELOG.md](CHANGELOG.md) 与 `backend/pyproject.toml` 版本的发布 PR。详见 [docs/CHANGELOG_AUTOMATION.md](docs/CHANGELOG_AUTOMATION.md)。

## 提交代码

1. 从 `main` 新建分支（示例：`fix/xxx`、`feat/xxx`）。
2. 尽量保持改动范围与 Issue/目标一致，避免无关格式化或大范围重排。
3. **提交信息**：标题与正文请使用**简体中文**；若使用约定式提交，类型前缀可保留英文（如 `feat:`），**说明仍用中文**。
4. 发起 Pull Request 时，请简要说明**动机、主要改动、如何验证**（例如本地执行的命令）。

## Issue

- **Bug**：复现步骤、期望与实际行为、环境（OS、Python/Node 版本、是否 Docker Qdrant 等）、相关日志或截图。
- **功能建议**：使用场景、是否愿意参与实现。

安全相关问题请勿公开 Issue，请按 [SECURITY.md](SECURITY.md) 联系维护者。

## 行为准则

参与本仓库即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

贡献将沿用仓库根目录 [LICENSE](LICENSE)（MIT）。
