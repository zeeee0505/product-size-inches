# 商品尺寸图厘米与英寸双标

把商品尺寸图上的标注统一为「厘米 / 英寸」。适合首饰和其他有尺寸标注的商品图片，支持扫描多层目录。

- `1.2 cm` → `1.2 cm / 0.5 in`
- `22 mm` → `2.2 cm / 0.9 in`
- `72+5 cm` → `72+5 cm / 28.3+2.0 in`

英寸四舍五入到一位小数。默认横排，空间不足时可排成两行。助手负责识别图片、定位尺寸文字并核对预览，脚本负责计算和局部排版。可备份后按原文件名替换，也可导出保留原文件名和子目录的结果 ZIP。

## 安装

从 [GitHub Releases](https://github.com/zeeee0505/product-size-inches/releases/latest) 下载 `product-size-inches-dual-unit.zip`。在 WorkBuddy 打开「技能 → 添加技能 → 上传技能」，选择 ZIP 或其中的 `product-size-inches` 文件夹。其他支持 Agent Skills 的助手可按各自的方式导入同一个目录。

运行环境需有 Python 3.10+、Pillow 10.1+，以及查看图片和读写工作区的能力。需要原位替换时，助手还需能写入原图目录。

## 调用

> 用 product-size-inches 处理这个文件夹。尺寸用厘米和英寸双标，英寸保留一位小数，核对并备份后原名替换。

云端助手可接收上传的原图 ZIP。请它处理后返回结果 ZIP，再将结果用于本地。完整说明见 [SKILL.md](product-size-inches/SKILL.md) 和 [跨平台用法](product-size-inches/references/hosts.md)。

## 验证

在仓库根目录运行以下命令。测试使用临时生成的图片。

```sh
python -m pip install -r requirements.txt
python -X utf8 tests/test_product_size_inches.py product-size-inches/scripts/size_chart.py
```
