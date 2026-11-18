# iOS 相册取证导出查看器（photos_viewer）

对 Photos.sqlite 查询导出 CSV 的本地取证可视化分析工具。适配两代查询导出格式：
ScottKjr 仓库（iOS11~17 各版本查询）与本项目 [`photos_sqlite_export`](../photos_sqlite_export/README.md)
（iOS11~26）——列按名称模糊匹配，互不锁定。全程本地解析，无网络请求。

## 使用（取证现场）

直接用浏览器打开 `dist/photos_viewer.html`（单文件、离线可用、file:// 直开），把查询导出的 CSV 拖进去即可。
重新构建：`npm run build` 后产物在 `dist/photos_viewer.html`。

## 动态自定义列

主表格默认只有固定列；勾选筛选栏的「**动态自定义列**」进入选列模式后：

- **点击详情面板任意字段**（含本行为空的字段——空值行以 `—` 显示，仍可加列）→ 该字段成为主表新列；
- 点击分类标题（设备/状态/时间…）旁的「**＋全部字段**」→ 分类内每个字段各加一列；
- 「**＋拼接成一列**」→ 整个分类拼接为一列（如 `Apple · iPhone 11 · 后置`），适合"找异类"类题目：一次排序即可把非本机拍摄的资产从多数派中分离出来；
- 展开「全部原始列」后点击任意原始列行 → 未映射的原始 CSV 列加为新列。

自定义列特性：

- 与固定列一致：点表头升/降序排序（数值列自动按数值比较）；
- 空值显示灰色 `—`，且**无论升/降序恒排末尾**；
- 防重复：重复添加 toast 提示「已在列中」，选列模式下已加字段行显示 ✓；
- 表头 ✕ 移除列；
- localStorage 持久化，换 CSV 载入时自动剔除新文件中不存在的列。

## 开发

```bash
npm install
npm run dev        # 开发服务器
npm run test       # vitest 回归测试（core 移植断言 + 自定义列功能测试）
npm run build      # 类型检查 + 构建离线单文件 dist/photos_viewer.html
```

### 结构

```
src/
  core/            # 纯逻辑（零 DOM，可直接单测）
    csv.ts         # RFC4180 CSV 解析
    schema.ts      # 列名归一化 + FIELD_DEFS 声明式字段映射 + 表头→逻辑列 mapping
    aggregate.ts   # 按 zAsset-zPK 聚合资产（相册/资源子表折叠、语义徽章、搜索文本）
    format.ts      # 语义美化（导入来源/前后摄/闪光灯/文件大小/时长/时间换算等）
  composables/
    customCols.ts  # 动态自定义列：field/raw/cat 三种列的取值、排序、回显校验
    useViewModel.ts# 筛选/排序/展开/自定义列操作 + localStorage 持久化
    useCsvLoad.ts  # 载入入口（校验/聚合/重置视图），window.__loadCSVText 测试钩子
  components/      # Dropzone / StatsBar / ControlsBar / AssetTable / DetailPanel / RawColumns / TimeCell / Badges
  state.ts         # 模块级单例状态（dataState/view/customCols/toast）
tests/             # vitest：core.test.ts（旧回归全量移植）+ customCols.test.ts（新功能）
```

### 测试钩子

`window.__loadCSVText(csvText, fileName)` 可在无文件对话框的情况下注入 CSV（开发服务器或自动化测试用）。
