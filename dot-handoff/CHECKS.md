# 交接文件核验记录

核验日期：2026-10-27（北京时间）。dot 重写文件后，10份原件全部齐全；每份字节SHA256都与原附件声明一致，已替代此前9/10的核验状态。

| 序号 | 原件路径 | SHA256 | 旧粘贴版 |
| --- | --- | --- | --- |
| 1 | `deployment-s22-s23-updated/0001-prepare-s22-s23-deployment.patch` | 通过 | 格式变化，哈希不同 |
| 2 | `deployment-s22-s23-updated/README.md` | 通过 | 格式变化，哈希不同 |
| 3 | `deployment-s22-s23-updated/compose.log` | 通过 | 一致 |
| 4 | `deployment-s22-s23-updated/preflight.json` | 通过 | 一致 |
| 5 | `deployment-s22-s23-updated/pytest.log` | 通过 | 一致 |
| 6 | `actions-acceptance-handoff/0001-actions-acceptance.patch` | 通过 | 格式变化，哈希不同 |
| 7 | `actions-acceptance-handoff/CI_ACCEPTANCE.md` | 通过 | 格式变化，哈希不同 |
| 8 | `actions-acceptance-handoff/COMMIT.txt` | 通过 | 一致 |
| 9 | `actions-acceptance-handoff/SHA256SUMS.txt` | 通过 | 一致 |
| 10 | `actions-acceptance-handoff/START_HERE.txt` | 通过 | 格式变化，哈希不同 |

两份补丁分别在其前置状态通过 `git apply --check` 后，以独立提交接入；接入后两份补丁均通过反向 `git apply --reverse --check`，没有对原补丁作猜测恢复。

原件按字节保留。部署补丁第34行含一个原始CR字节，属于删除行内容，哈希与声明完全匹配；未为统一换行而改写该原件。旧附件的粘贴拆分版统一为UTF-8无BOM、LF、单个末尾换行，移除了文件间分隔空行。完整附件另按原始字节保留。

本轮本地检查：156项纯/mock测试通过；排除4项API数据库测试并取消选择2项数据库发布测试，6项真实数据库测试交由Actions执行。223局离线源预检、前端typecheck、Python语法、YAML结构和diff空白检查通过。首次pytest临时目录权限错误通过将临时目录和缓存移至工作区解决，未修改测试逻辑。

原 `pytest.log`、`preflight.json`、`compose.log` 和两份包说明仍是dot交付时的历史证据。本轮YAML结构检查不等于Docker Compose schema验证；未在本机执行Docker镜像构建、容器运行或正式数据库写入。真实Actions验收状态见 [接续记录](INTEGRATION.md)。

旧0字节部署ZIP已保留于source目录。新的 `dot-handoff-organized.zip` 是整理归档包，不是旧ZIP的恢复副本；其所有成员均与本地文件逐字节核对。
