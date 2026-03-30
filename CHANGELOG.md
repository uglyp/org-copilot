# 变更记录

本文件遵循用户可见的**语义化摘要**：重要功能、修复与破坏性变更。版本号与 [backend/pyproject.toml](backend/pyproject.toml)、前端 `package.json` 对齐时可在此同步更新。

**自动维护：** 推送 `main` 后可用 Release Please 根据约定式提交打开「发布 PR」并更新本文件与后端版本，见 [docs/CHANGELOG_AUTOMATION.md](docs/CHANGELOG_AUTOMATION.md)。

## [0.1.0] - 2026-03-30

### 新增

- 根目录开源基建：MIT 许可证、[CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md)、[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- GitHub Actions CI：后端 `uv sync` 与导入校验，前端 `npm install` 与生产构建。
- Issue 模板：缺陷报告与功能建议。
- README 面向发现与协作的摘要、架构示意、Roadmap、目录与截图占位说明。
- [docs/GITHUB_REPOSITORY_METADATA.md](docs/GITHUB_REPOSITORY_METADATA.md)：仓库 Description 与 Topics 的推荐文案（需在 GitHub About 中手动填写）。
