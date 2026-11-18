# samples/ —— 合成样本数据

本目录所有文件均为**程序合成的演示/测试数据，不含任何真实设备信息**，可安全提交。

| 文件 | 说明 |
|---|---|
| `Photos_ios26_synthetic.sqlite` | 合成的 iOS 26 结构 Photos 库（5 资产，含相册/内部资源乘行、中文逗号引号文件名等边界数据）。由 `../tests/make_synthetic_db.py` 生成（版本 key `'26'`），可随时重新生成或扩展为其他版本（11 ~ 26 共 10 档） |
| `Photos_ios26_synthetic_basic.csv` | 用本工具对上面合成库的 basic profile 导出结果（218 列 × 8 行，UTF-8 BOM），也可作为 photos_viewer 的手测样本 |
| `export_report.txt` | 上述导出的结构探测报告 |

重新生成：

```bash
cd ..   # photos_sqlite_export/
python - <<'EOF'
import sys, os
sys.path.insert(0, 'tests')
import make_synthetic_db as m
m.build('samples/Photos_ios26_synthetic.sqlite', '26')
EOF
python photos_export.py samples/Photos_ios26_synthetic.sqlite -o samples
```
