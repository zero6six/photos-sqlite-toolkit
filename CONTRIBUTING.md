# CONTRIBUTING

## 开发环境

- `photos_sqlite_export`：Python ≥ 3.8，仅标准库，无需安装任何包。
- `photos_viewer`：Node ≥ 20，`npm install` 后 `npm run dev`。

## 测试

```bash
# 导出器：30 个测试（10 个 iOS 版本合成库 + 6 个 WAL 差分场景）
cd photos_sqlite_export
python -m unittest discover -s tests

# 查看器：57 个 vitest 测试（含 WAL 差分与导出器 CSV 契约测试）
cd photos_viewer
npm test
```

CI（`.github/workflows/ci.yml`）在 ubuntu/windows × Python 3.8–3.13 上跑同样的测试。

## 可选：逐值对照测试（差分测试）

`tests/test_export.py` 里有 3 个对照测试，会把本工具的输出与两份上游查询
**逐值比对**（合成库上）。它们需要上游素材在本地，缺失时自动 skip：

```bash
# 素材放到 photos_sqlite_export 的上级目录（即仓库根目录）：
git clone https://github.com/ScottKjr3347/iOS_Local_PL_Photos.sqlite_Queries
git clone https://github.com/abrignoni/iLEAPP
```

或用环境变量指定任意位置：

```bash
PSE_REPO=/path/to/iOS_Local_PL_Photos.sqlite_Queries \
PSE_ILEAPP=/path/to/iLEAPP \
python -m unittest discover -s tests
```

Windows（Git Bash）下环境变量写法相同；CMD 用 `set`、PowerShell 用 `$env:`。

## 重建 catalog.json

`catalog.json` 是运行时唯一需要的数据文件（255 列 / 17 JOIN），由
`tools/build_catalog.py` 从上面两份上游素材生成。**不重建就不需要素材**；
只有修改了合并规则或上游查询更新时才需要：

```bash
cd photos_sqlite_export
python tools/build_catalog.py \
    --repo  <iOS_Local_PL_Photos.sqlite_Queries 目录> \
    --ileapp <iLEAPP 源码目录> \
    --out catalog.json
```

重建后跑全量测试确认行为不回退。来源与许可说明见 [NOTICE.md](NOTICE.md)。

## 重构语义红线（改代码前必读）

以下行为是设计核心，"顺手简化"最容易弄坏的地方：

1. **JOIN 解析必须三态**（ok / defer / fail）。目录里 JOIN 按别名字母序
   排列，依赖可能尚未就绪——把 defer 误判为 fail 会在新版 iOS 上凭空丢列。
2. **同名别名按每条查询自己的 ON 条件定规范名**，不能按别名全局改名
   （`zCldMastMedData` 在不同版本查询里指不同的连接侧）。
3. **`locations` 过滤器用 `ZLATITUDE != -180.0`**，不能用 `> 0`（会漏南纬）。
4. **过滤器不适用时跳过该 CSV 并写明原因**，绝不输出未过滤的结果冒充。
5. **`basic` profile 一个资产可占多行**（相册/内部资源乘行，与上游查询
   语义一致）；要单行用 `--profile very-basic`。
6. **原数据库文件只读打开**（`mode=ro`，快照遍用 `immutable=1` 强制忽略
   WAL）。WAL 差分的 checkpoint 只发生在输出目录 `_wal_work/` 里的**副本**
   上（跑完即删）——原件不动是差分可重复执行的前提，不要改成原地
   checkpoint。
7. **WAL 差分按 `zAsset-zPK` 的行集合比对**（不是逐 CSV 行）：basic 一资产
   多行，逐行比对会满屏假差异。四态 unchanged/added/removed/modified，
   removed 行的数据取自快照遍。

## 版本与发布

- 版本号三处同步：`photos_export.py` 的 `__version__`、`pyproject.toml`
  的 `version`、git tag。
- viewer 构建产物 `dist/photos_viewer.html` 随 Release 附带：
  `cd photos_viewer && npm run build`。
- 合成样本再生成方法见 `photos_sqlite_export/samples/README.md`。
