# 安装与调用

## WorkBuddy 桌面版

在「专家·技能·连接器 → 技能 → 添加技能 → 上传技能」选择通用 ZIP。若文件选择器只接受目录，则选解压出来的 `product-size-inches` 文件夹。可按 [WorkBuddy 帮助](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market) 找到入口。导入后在对话中选中该技能，把图片文件夹设为工作目录或提供助手能访问的完整路径，发送下面的调用示例。

## 其他助手

- 支持 Agent Skills 的助手：通过其自定义技能入口导入整个 ZIP 或 `product-size-inches` 文件夹。`SKILL.md` 与 `scripts/`、`references/` 必须保持原来的相对位置。[Agent Skills 格式说明](https://agentskills.io/specification)。
- 能读取附件和运行代码但没有技能入口的助手：把技能 ZIP 作为附件，并让它解压、读取其中的 `SKILL.md`，按需读取参考和运行附带脚本。另附原图 ZIP。无需使用专属斜杠或 `$` 命令。
- 能读取本地目录才可处理本机文件；运行在云端时上传图片或原图 ZIP，并用结果 ZIP 交付。只有文字聊天、无图片读取或代码执行能力的助手无法自动跑完整工作流。

## 调用示例

本地：请使用 `product-size-inches` 处理我选中的商品图片目录。尺寸用厘米和英寸双标，英寸保留一位小数，核对和备份后原名替换。

云端：请读取附件里的 `product-size-inches/SKILL.md` 并执行这套流程。另一份 ZIP 是原图。尺寸用厘米和英寸双标，英寸保留一位小数，按原文件名和子目录返回结果 ZIP。

运行前在助手实际执行的环境检查 Python 3.10+ 和 Pillow 10.1+；Windows 可用 `py -3`，macOS/Linux 可用 `python3`，也可直接用已有的 `python`。依赖安装及脚本命令见[图片标注脚本](image-edits.md)。
