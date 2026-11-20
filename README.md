# photos-sqlite-toolkit

iOS 照片库（`Photos.sqlite`）取证工具链：**把任意 iOS 版本的照片库导出成 CSV，再在离线网页里做可视化分析**。全程本地运行、无网络请求、不改动证据文件，可直接用于取证现场。

[English](docs/README.en.md)

## 为什么需要它

分析 iOS 照片库的社区标准做法是运行一套现成的 SQL 查询合集（Scott Koenig 的 `iOS_Local_PL_Photos.sqlite_Queries`），但该合集按 iOS 版本各写一份查询、写死表名列名——Core Data 关联表编号随版本漂移（`Z_28ASSETS` → `Z_29` → `Z_30` → `Z_33`），在 iOS 26 上全部失败。

本工具集把它重构成**不依赖 iOS 版本号**的通用方案：运行时探测库结构，从 `Z_PRIMARYKEY` 按实体含义找到关联表，缺表缺列自动裁剪，尽力产出结果。

## 组成

| 组件 | 说明 |
|---|---|
| [`photos_sqlite_export/`](photos_sqlite_export/README.md) | 导出 CLI。纯 Python 标准库，`photos_export.py` + `catalog.json` 两个文件复制即用；输出 UTF-8 带 BOM 的 CSV（Excel 直开）+ 结构探测报告 |
| [`photos_viewer/`](photos_viewer/README.md) | 查看器。Vue 3 构建的**离线单文件 HTML**（`file://` 直开），把导出 CSV 拖进去即可：按资产聚合、语义徽章（含 WAL 差分标记）、筛选排序、动态自定义列 |

```
Photos.sqlite ──► photos_export.py + catalog.json ──► CSV（UTF-8 BOM）──► photos_viewer.html
                 （结构探测/列裁剪/过滤器）                              （本地可视化分析）
```

## 快速开始

### 1. 导出（需要 Python ≥ 3.8）

```bash
cd photos_sqlite_export

# 没有检材？用合成样本走一遍流程：
python photos_export.py samples/Photos_ios26_synthetic.sqlite -o samples_demo

# 真实检材（库以只读方式打开，绝不会被改动）：
python photos_export.py Photos.sqlite -o out                # 主 CSV + 报告
python photos_export.py Photos.sqlite -o out --all-filters  # 隐藏/最近删除/收藏/定位/调整/同步 各一份

# 同目录有非空 Photos.sqlite-wal 时自动进入差分导出：
# 新增/删除/修改 的资产会在 CSV 的 wal-diff-status 列标出（--no-wal-diff 可关）
```

更多参数（`--profile very-basic`、`--where`、`--dump-sql` 等）与退出码语义见[子项目 README](photos_sqlite_export/README.md)。

### 2. 查看（无需安装）

```bash
# 方式 A：从 Release 下载 photos_viewer.html（单文件、离线可用），浏览器直接打开
# 方式 B：自行构建
cd photos_viewer && npm install && npm run build   # 产物 dist/photos_viewer.html
```

把 CSV 拖进页面即可。已知行为：`basic` 导出一个资产可能占多行（相册/内部资源乘行），查看器会自动按 `zAsset-zPK` 折叠回单资产。

## 测试

```bash
cd photos_sqlite_export && python -m unittest discover -s tests   # 30 个测试（含 10 个 iOS 版本合成库 + WAL 差分）
cd photos_viewer && npm test                                      # 57 个测试（含与导出器 CSV 的契约测试）
```

## 已知边界（诚实声明）

- 结构验证覆盖 iOS 11–26（合成库 + 真实 iOS 26 结构库）；**值级正确性仅在合成库上做过逐值对照**。
- 合成样本数据在 `photos_sqlite_export/samples/`，可复核再生成，不含任何真实设备数据。
- 更多细节见[子项目 README 的"已知状态"](photos_sqlite_export/README.md)。

## 致谢与第三方来源

本工具集的查询知识站在两位 forensic 社区作者的工作之上：

- **Scott Koenig**（[theforensicscooter.com](https://theforensicscooter.com)）——照片库 SQL 查询合集的原作者
- **Alexis Brignoni**——[iLEAPP](https://github.com/abrignoni/iLEAPP)（MIT），这些查询在其中的延续维护

`catalog.json` 为衍生数据文件，逐列记录了来源溯源；完整的来源说明、commit 号与许可现状见 [NOTICE.md](NOTICE.md)。

## 许可

本项目代码与文档采用 [MIT](LICENSE)。`catalog.json` 含第三方衍生内容，其归属与许可说明见 [NOTICE.md](NOTICE.md)。

## 参与贡献

测试跑法、目录（catalog）重建步骤、以及重构时**不能破坏的语义红线**，见 [CONTRIBUTING.md](CONTRIBUTING.md)。
