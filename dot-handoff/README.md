# dot 交接材料整理

当前开发与dot复核职责遵循[工程约定](../AGENTS.md#开发与复核)。本目录保留历史交付原件；其中的分支名、开发分工和计划描述当时状态。

10/10 份原件均已通过附件声明的 SHA256 核验。部署和 Actions 补丁曾在 `ci/full-acceptance` 分别接入，现已同步至唯一的 `main` 分支；正式站点未部署。

- [核验记录](CHECKS.md)：原件完整性、粘贴版差异和本地检查结果。
- [接续记录](INTEGRATION.md)：提交、分支、检查和真实 Actions 状态。
- [部署交接说明](deployment-s22-s23-updated/README.md)：完整部署补丁及3份历史验证记录。
- [Actions 接续说明](actions-acceptance-handoff/START_HERE.txt)及[验收设计](actions-acceptance-handoff/CI_ACCEPTANCE.md)：独立增量补丁及其原校验清单。
- [机器可读清单](manifest.json)和[整理包实际校验和](SHA256SUMS.actual.txt)。

[GitHub Actions 验收](https://github.com/fengmaker/LangRenSha/actions/runs/40483537880)：已结束：success。具体证据见接续记录。

两包目录内的10份原件保留原始字节。`raw-pasted/` 为旧附件的忠实拆分版，其中两份补丁和部分文档有格式丢失，仅供追溯；不要用它们替代已验证原件。完整附件保存在 `source/pasted-original.txt`，原0字节占位ZIP保存在 `source/empty-placeholder-deployment-s22-s23-handoff-updated.zip`。

两份原始交接说明中的“尚未推送”等文字描述 dot 交付时的状态，当前本地接续状态以接续记录为准。补丁已经接入，不要重复应用。
