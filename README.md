# QuarkPanTool

[![Python Version](https://img.shields.io/badge/python-3.11.6-blue.svg)](https://www.python.org/downloads/release/python-3116/)
[![Latest Release](https://img.shields.io/github/v/release/ihmily/QuarkPanTool)](https://github.com/ihmily/QuarkPanTool/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/ihmily/QuarkPanTool/total)](https://github.com/ihmily/QuarkPanTool/releases/latest)
![GitHub Repo stars](https://img.shields.io/github/stars/ihmily/QuarkPanTool?style=social)

QuarkPanTool 是一个简单易用的小工具，帮助用户批量转存分享文件、批量生成分享链接、批量下载夸克网盘文件，并支持一键自动化下载他人分享链接。

## Home

Hmily edited this page on Jul 5, 2025 · 7 revisions  
QuarkPanTool 使用教程

## 功能特点

- 稳定登录：基于 Playwright 支持网页登录夸克网盘，无需手动获取 Cookie。
- 命令行界面：简洁直观的交互，快速完成文件转存与下载。
- 批量能力：支持批量转存、批量分享、批量下载。
- 无需 VIP：已绕过 Web 端文件大小下载限制。
- 一键下载：选项(7) 自动完成“转存 → 分享 → 下载 → 清理”全流程。

## 环境与依赖

如果不想自己部署环境，可下载打包好的可执行文件（exe）压缩包 [QuarkPanTool](https://github.com/ihmily/QuarkPanTool/releases) ，解压后直接运行。

手动部署：

```
git clone https://github.com/ihmily/QuarkPanTool.git
pip install -r requirements.txt
playwright install firefox
```

运行：

```
python quark.py
```

支持的命令行参数：

- `--download "<分享链接>"`：自动化下载模式（同选项 7），直接执行一键下载流程。支持带密码的链接（如 `.../s/abcd?pwd=1234`）。
- `--cookie "<Cookie 字符串>"`：可选；如传入会写入 config/cookies.txt 并优先使用该值。
- `--path "<本地保存路径>"`：可选；指定下载文件的本地保存目录（默认为 `output/downloads`）。

**示例**：

```bash
# 基础一键下载
python quark.py --download "https://pan.quark.cn/s/abcd?pwd=123456"

# 指定 Cookie 和 保存路径
python quark.py --cookie "你的Cookie" --download "https://pan.quark.cn/s/abcd" --path "D:\Downloads"
```

## 首次运行

### Windows 环境

- 首次运行可能较慢，请耐心等待。程序会自动打开浏览器窗口要求登录夸克网盘；若界面未主动弹出，请查看底部状态栏确认是否有打开的浏览器窗口。
- 登录完成后，请不要手动关闭浏览器。回到软件界面按 Enter 键，浏览器会自动关闭并保存登录信息。下次运行无需重复登录。

### Linux 环境

- 请自行在网页获取 Cookie，并填入 config/cookies.txt 文件后使用。

## 切换保存目录

- 输入文件夹 ID：系统会提示输入保存位置的文件夹 ID。
- 选择保存位置：
  - 输入 0 代表保存在网盘根目录。
  - 直接按回车将显示网盘文件夹列表，选择对应序号即可。
  - 切换保存路径仅支持根目录下的一级文件夹。

## 功能选项

- 选项(1)：通过他人分享地址将文件转存到自己的网盘。支持单个或批量地址。批量模式请在 config/url.txt 中填写分享地址（一行一个）。如果分享地址有密码，在地址末尾加上 `?pwd=提取码`，例如分享地址为 `https://pan.quark.cn/s/abcd`，提取码是 `123456`，则应输入 `https://pan.quark.cn/s/abcd?pwd=123456`。
- 选项(2)：将自己网盘中的文件夹批量生成分享链接。仅对文件夹生效，文件会被忽略。分享完成后会将链接写入程序目录下 `output/share_url.txt` 文件。
- 选项(3)：切换保存路径。输入的 ID 为 0 表示保存在网盘根目录。仅支持根目录下一级文件夹的切换。
- 选项(4)：创建网盘保存目录。仅支持在根目录下创建一级文件夹。
- 选项(5)：下载文件到本地。必须是您网盘中的文件。将需要下载的文件或对应文件夹（支持多级）创建分享链接后粘贴到软件进行下载（注意链接要去掉中文汉字）。文件下载成功后保存到程序目录下 `output/downloads` 文件夹。
- 选项(6)：重新登录账号。可切换登录其他账号。也可手动清空 `config/cookies.txt` 后启动软件以重新登录。
- 选项(7)：一键下载他人分享链接（自动化）。输入分享地址后，程序将自动执行：
  74→ - 检测分享是否为当前登录用户所创建；若是，则直接下载。
  75→ - 若不是：自动创建临时目录 → 转存分享文件至临时目录 → 批量生成分享链接 → 根据生成的链接批量下载到本地 → 取消分享并删除临时目录。
  76→ - 自动化模式也可通过命令行执行：
  77→ `bash
78→    python quark.py --download "https://pan.quark.cn/s/xxxx?pwd=yyyyyy"
79→    `
  80→ - 如需临时指定 Cookie 和保存路径：
  81→ `bash
82→    python quark.py --cookie "<Cookie字符串>" --download "https://pan.quark.cn/s/xxxx?pwd=yyyyyy" --path "D:\Downloads"
83→    `
  84→
  85→## 注意事项

- 执行批量转存前，请先在 `config/url.txt` 填写分享地址（一行一个）。
- 如分享地址有提取码，需在地址末尾加 `?pwd=提取码`（例如 `https://pan.quark.cn/s/abcd?pwd=123456`），程序会自动处理提取码。
- 选项(7) 的自动化流程会在结束时取消临时分享、删除临时目录，以保持网盘整洁。

## 效果演示

![ScreenShot1](./images/Snipaste_2024-09-23_19-02-03.jpg)

## 许可证

QuarkPanTool 使用 [Apache-2.0 license](https://github.com/ihmily/QuarkPanTool#Apache-2.0-1-ov-file) 许可证，详情请参阅 LICENSE 文件。

---

**免责声明**：本工具仅供学习和研究使用，请勿用于非法目的。由使用本工具引起的任何法律责任，与本工具作者无关。
