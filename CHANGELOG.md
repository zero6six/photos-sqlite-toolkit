# Changelog

版本号只在此处维护（仓库级，两个子项目共用），git tag 取 `v<版本号>`。
每个版本发布时在此追加一节。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## 0.4.0 - 2026-11-22

- **exporter：WAL 差分升级为逐提交回放**。此前只对比"主库快照 vs 合并
  WAL 后的终态"两态——资产在 WAL 内部**先创建后删除**（从未 checkpoint
  进主库）时两态都看不到。现在解析 WAL 帧的提交边界（SQLite 文件格式），
  在副本上逐个提交回放全部中间状态（0=快照，1..K=各提交前缀），所以：
  - 创建后又在 WAL 内删除的资产以 `removed` 出现，行值取**最后一次被
    看见的状态**——例如带着移入垃圾桶的标记与时间，"生成后 N 秒被删"
    类题目可直接从 CSV 作答；
  - 新增 `wal-first-commit` / `wal-last-commit` 溯源列（0=主库快照）；
  - `--wal-replay-limit N`（默认 2000）防巨型 WAL，超限截断并提示改用
    专用 carve 工具（如 sqlite4n6）；
  - 不复制 `-shm`；每个回放状态用独立子目录副本，原件字节不变、可重复
    执行。回滚日志/空闲块/未提交帧的深度恢复仍属 carve 工具领域。
  - **部分 checkpoint 的活体检材兼容**：主库被 checkpoint 到中段时，早于
    前沿的提交前缀天然不可读（跳过并在报告注明，那段历史已合并进主库）；
    中间态若因跨表页时代混杂使完整查询失败，主 CSV 自动降级为 ZASSET 单表
    探针，删除类证据依然可恢复（真实检材实测：恢复出"生成后 12 秒被移入
    垃圾桶"的资产，含删除时间戳）。

## 0.3.0 - 2026-11-20

- **版本体系统一**：仓库级单一版本号（本文件），git tag 跟随。子项目不再
  各自维护版本——删除 exporter 的 `__version__`/`--version`、
  `pyproject.toml`、viewer `package.json` 的 `version` 字段及 CI 对应步骤。
- **修复 viewer 排序错序**（按显示文本 parseFloat 导致单位倍率丢失）：
  - 大小列：改为按原始字节数值排序（此前 `103.4KB` 会排在 `5.30MB` 之后）；
  - 时长列：改为按原始秒排序（此前 `3分05秒` 会被当成 `3`，排在 `45 秒` 前面）；
  - GPS 列：改为按纬度数值排序（此前纬度 `9.x` 会排在 `27.x` 之后）；
  - 自定义列数值检测收紧为纯数字判定，杜绝 `"2.43 MB"` 这类前缀可解析串
    被误判成数值列。

## 0.2.0 - 2026-11-20

- **exporter：WAL 差分导出**。检出非空 `-wal` 时自动双遍导出（快照遍
  `immutable=1` + checkpoint 副本遍，原文件不动、可重复执行），按
  `zAsset-zPK` 合并输出 `wal-diff-status` 列（unchanged / added /
  removed / modified），removed 行保留删除前快照值；filter 与 `--where`
  同走差分；`--no-wal-diff` 恢复单遍；`--keep-wal-work` 保留工作副本。
- **viewer：WAL 差分可视化**。状态徽章（新增/删除/修改）、筛选栏计数
  chips、removed 资产删除线样式、统计栏汇总；旧 CSV 不受影响。
- **viewer↔exporter 契约测试**（`exporterCsv.test.ts`）：以入库合成样本
  过真实解析聚合管线，并修复 `zAsset-Added Date` 表头不被映射的缺口。

## 0.1.0 - 2026-11-18

- 首个开源版本（MIT）。
- **photos_sqlite_export**：单文件纯标准库 CLI，结构探测导出 CSV——任意
  iOS 版本可用（11–26），Core Data 关联表按 `Z_PRIMARYKEY` 实体含义发现，
  缺表缺列自动裁剪；6 个过滤器预设；`--dump-sql`/`--profile` 等。
- **photos_viewer**：Vue 3 离线单文件 HTML 查看器——按 `zAsset-zPK` 聚合、
  语义徽章、筛选排序、动态自定义列、时区换算。
- 合成样本（iOS 26）与再生成说明入库；NOTICE.md 记录查询目录的第三方
  溯源（Scott Koenig 查询合集、iLEAPP）。
