# photos_sqlite_export

把任意 iOS 版本的 `Photos.sqlite` 导出成 CSV。不需要知道 iOS 版本，缺表缺列时自动忽略，尽量产出结果。

> 初版说明（开发中）。当前状态见文末"已知状态"。

## 快速使用

需要 Python 3.8+，只用标准库。`photos_export.py` 和 `catalog.json` 必须放在同一目录。

```bash
# 基础导出：一份 CSV + 一份报告
python photos_export.py Photos.sqlite -o out

# 同时按预设过滤器各出一份（隐藏、最近删除、收藏、有位置、有调整、SWY 同步）
python photos_export.py Photos.sqlite -o out --all-filters

# 只要其中几个
python photos_export.py Photos.sqlite -o out --filter hidden trashed

# 每个资产只占一行（不连相册和内部资源表）
python photos_export.py Photos.sqlite -o out --profile very-basic

# 自定义条件，别名同原查询（zAsset、zAddAssetAttr、zGenAlbum ...）
python photos_export.py Photos.sqlite -o out --where "zAsset.ZFAVORITE = 1"

# 把最终 SQL 打到 stderr，可以贴到别的工具里跑
python photos_export.py Photos.sqlite -o out --dump-sql 2> final.sql
```

## WAL 差分导出（v0.2.0 起，自动）

目录里存在非空的 `Photos.sqlite-wal` 时（活体提取的常见状态），导出自动变成
两遍差分：第一遍读主库上次 checkpoint 的快照，第二遍读
**副本**上 checkpoint 合并后的完整状态（原文件不动，重跑结果一致）。两边按
`zAsset-zPK` 合并成一张 CSV，多出一列 `wal-diff-status`：

| 值 | 含义 | 行数据取自 |
|---|---|---|
| `unchanged` | 两遍一致 | 完整状态 |
| `added` | WAL 里新增的资产 | 完整状态 |
| `modified` | WAL 里有改动（含相册隶属变化） | 完整状态 |
| `removed` | WAL 里已删除的资产 | 快照（完整状态里已没有这行） |

- 差分对 `--filter` / `--all-filters` / `--where` 的 CSV 同样生效。
- 两侧结构可能不同（WAL 里可以有 DDL），列取并集，缺失侧补空。
- `--no-wal-diff` 恢复普通单遍导出；`--keep-wal-work` 保留
  `<输出目录>/_wal_work/` 里的 checkpoint 副本备查（默认删除）。
- `-wal` 缺失或 0 字节时就是普通导出，不进差分。

不加 `-o` 时输出到数据库所在目录下的 `photos_export/`。

## 输出

| 文件 | 内容 |
|---|---|
| `<库名>_basic.csv` | 主导出 |
| `<库名>_basic_<过滤器>.csv` | 每个过滤器一份 |
| `<库名>_basic_custom.csv` | `--where` 的结果 |
| `export_report.txt` | 识别到的结构、去掉的 JOIN 和列及原因、每份 CSV 的行列数 |

CSV 是 UTF-8 带 BOM，Excel 可直接打开。BLOB 列写成 `0x` 开头的十六进制。

## 参数

| 参数 | 作用 |
|---|---|
| `-o DIR` | 输出目录 |
| `--profile basic\|very-basic` | `basic`（默认）连全部表；`very-basic` 每资产一行 |
| `--filter NAME ...` | `hidden` `trashed` `favorite` `locations` `adjusted` `syndication` |
| `--all-filters` | 全部过滤器 |
| `--where "SQL"` | 自定义 WHERE |
| `--keep-missing` | 缺失的列保留表头、值为空（默认直接去掉） |
| `--no-wal-diff` | 有非空 `-wal` 时也不做差分，普通单遍导出 |
| `--keep-wal-work` | 保留差分用的 checkpoint 副本目录 |
| `--limit N` | 只取前 N 行 |
| `--dump-sql` | 打印最终 SQL |
| `--list` | 查看目录里有哪些 profile 和过滤器 |

## 退出码

- `0`：要求的 CSV 都生成了（缺列被忽略属于正常）。
- `1`：有 CSV 被跳过。常见原因是过滤器在该版本不适用，例如 iOS 15 之前没有 `syndication` 用的列；主 CSV 仍会生成。
- `2`：文件打不开，或里面没有 `ZASSET` / `ZGENERICASSET`。

## 需要知道的行为

- **`basic` 下一个资产可能占多行**：连了相册关联表和内部资源表，和原查询一致。数资产个数请看 `zAsset-zPK` 去重，或用 `--profile very-basic`。
- **关联表按库结构自动找**：`Z_28ASSETS`、`Z_30ASSETS`、`Z_33ASSETS` 这类编号从 `Z_PRIMARYKEY` 里读，不靠版本号。报告第二行会写找到的是哪张表。
- **枚举文字用的是最新版本的写法**：旧版本库里部分 CASE 列的说明文字和原版本 SQL 不逐字相同，数字本身不变。
- **过滤器不适用时不出文件**：不会输出一份没过滤的结果冒充。
- **`locations` 的条件是 `ZLATITUDE != -180.0`**：原仓库的 `> 0` 会漏掉南纬。
- **`adjusted` 自动选列**：有 `ZHASADJUSTMENTS` 用它，没有（iOS 18 起）用 `ZADJUSTMENTSSTATE > 0`。
- **数据库只读打开**：原文件不会被改动；差分模式的 checkpoint 发生在输出目录里的副本上，跑完即删（`--keep-wal-work` 保留）。
- **WAL 差分**：见上文专节。`-shm` 不参与差分（不复制它，快照用 `immutable=1` 强制忽略）。

## 列从哪来

`catalog.json` 合并了两份来源，共 255 列、17 个 JOIN：

- 归档仓库 `iOS_Local_PL_Photos.sqlite_Queries` 的 Basic / Very-Basic（iOS 11–17）
- iLEAPP 的 `Ph001`、`Ph002`（Scott Koenig 维护，iOS 11–26）

同一列在两边都有时，用较新来源的表达式和列名。重新生成：

```bash
python tools/build_catalog.py --repo <原仓库目录> --ileapp <iLEAPP 源码目录> --out catalog.json
```

## 已知状态

- **只在合成库上跑过**，没有在真实设备数据上验证。合成库是按各版本查询反推出来的表结构，iOS 11、12、13、14、15、16、17、17.6、18、26 各一个，全部能导出。
- **iOS 26 的结构知识来自 iLEAPP 的代码**，iLEAPP 自己列出的测试镜像最高到 iOS 18.7。
- **测试 30 个全部通过**（`python -m unittest discover -s tests`），含三组逐值对照：与原仓库 Basic（iOS 13–17）、Very-Basic（iOS 11、12）、iLEAPP Ph002 的 iOS 26 查询在合成库上比对普通列和日期列的值。CASE 列只比形态不比文字（枚举文字用最新版本的写法）。WAL 差分有专门的崩溃写 WAL 夹具测试（增/删/改四分类、原件不被改动、过滤器走差分路径）。
- 合成 iOS 26 库上导出 218 列，其余 37 列因表或列不存在被去掉，明细在报告里。
- 没移植的查询组：Large_Reference、Albums-Only、Albums-with-Assets、iCloudLink-CMMoment、IntResou-iCldPhotos、MigrationHistory。
- 运行测试需要把原仓库和 iLEAPP 源码放在本项目的同级目录（缺了会跳过对照测试）。
