# BiliBiliVideo-TRANS

轻量化实现把 Bilibili 客户端（macOS）下载的 m4s 分片文件夹合并为单个可播放 mp4 的纯 CLI 工具。自动去除反盗版 9 字节头、识别视频/音频流、嵌入封面，全程带进度条与时间统计。

---

## 1. 项目结构

```
BiliBiliVideo-TRANS/
├── merge.py              # 唯一的程序文件（Python CLI）
├── setup.sh              # 一键检查/安装依赖（Python / ffmpeg / ffprobe）
├── README.md             # 用户文档（本文件）
├── LICENSE               # MIT License
├── .gitignore            # 默认排除版权数据、中间产物、本地配置
├── input_folder/         # 输入：把 B 站下载的 cid 文件夹放这里
│   └── <cid>/            #   cid 是一串数字（如 260xxx）
└── output_video/         # 输出：合并后的 mp4 自动生成在这里
    └── *.mp4             #   对应mp4文件
```

### 被处理的 cid 文件夹内部结构

B 站客户端下载一个视频后会生成以 `cid` 命名的目录（cid 是一串数字），例如 `input_folder/500xxx/`（下文 `260xxx`、`500xxx` 均为 cid 的脱敏示例，实际目录名是一串完整数字）：

```
500xxx/
├── 500xxx-1-xxxxx.m4s   # 视频或音频分片（fMP4 + 9 字节反盗版头）
├── 500xxx-1-xxxxx.m4s   # 同上，与上一个互补：一个视频流、一个音频流
├── videoInfo.json       # 视频元数据（标题、UP 主、cid、bvid、时长、status）
├── .videoInfo           # 与 videoInfo.json 内容相同的副本
├── .playurl             # 调 B 站 playurl 接口返回的原始 JSON
├── view                 # 视频详情接口原始数据
├── dm1, dm2, ...        # 弹幕元数据分片（protobuf 编码）
├── image.jpg            # 单个分 P 的封面（会被 merge.py 嵌入 mp4）
├── group.jpg            # 合集（多 P）封面
└── .DS_Store            # macOS 系统文件
```

对应文件名命名约定：`{cid}-{page}-{codecid}.m4s`。



## 2. 一键配置

依赖只有 Python 3.9+ 和 ffmpeg（含 ffprobe）。macOS 上跑这一行就行：

```bash
bash setup.sh
```

脚本会自动：
- 检查 Python 版本，过低时报错
- 检查 ffmpeg / ffprobe，缺失时通过 Homebrew 自动安装
- 创建 `input_folder/` 和 `output_video/` 目录

如果还没有 Homebrew，先装：https://brew.sh



## 3. 使用方法

### 完整参数

```ba
#!/usr/bin/env bash

# 批量处理 input_folder 内的cid文件夹
python3 merge.py

# 单目录处理
python3 merge.py input_folder/260xxx/

# 指定输出文件名（单目录）
python3 merge.py input_folder/260xxx/ -o "output_video/a.mp4"

# 不写入封面
python3 merge.py --no-cover

# 调试模式（详细日志 + 保留临时文件）
python3 merge.py -v --keep-temp

# 组合示例
python3 merge.py input_folder/260xxx/ -o "output_video/a.mp4" -v --keep-temp --no-cover
```

### 完整参数

```
usage: merge.py [-h] [-o OUTPUT] [--keep-temp] [--no-cover] [-v] [directory]

位置参数:
  directory             输入目录（默认: input_folder/）

选项:
  -h, --help            显示帮助
  -o, --output PATH     输出 mp4 路径（仅单目标时生效；默认 output_video/<title>.mp4）
  --keep-temp           保留 .cleaned.mp4 中间文件
  --no-cover            不嵌入封面（默认嵌入 image.jpg 作为 attached_pic）
  -v, --verbose         打印 ffprobe 结果与完整 ffmpeg 命令
```

### 输出示例

```
发现 2 个待处理目录
开始时间: yyyy-mm-dd hh:mm:ss

[1/2] 260xxx  →  output_video/【视频标题1】.mp4
  封面: image.jpg
  开始时间: hh:mm:ss
  [███████████████████████░]  99.9% | 5:52/5:53 | 剩余 0:00 | 1335x
  结束时间: hh:mm:ss
  耗时: 0:00  →  【视频标题1】.mp4
···

==================================================
总计 2 个 | 成功 2 | 失败 0
开始: yyyy-mm-dd hh:mm:ss
结束: yyyy-mm-dd hh:mm:ss
耗时: 0:01
```

> 进度条在真实终端会以单行刷新；如果通过管道（如 `| cat`、`> log.txt`）捕获输出，会看到所有中间帧拼在一起，属正常现象。



## 4. 合并原理

```
*.m4s  ──[strip 9字节头]──►  *.cleaned.mp4  ──[ffprobe]──►  video/audio  ──[ffmpeg -c copy]──►  out.mp4
```

**9 字节头**: B 站客户端下载的 m4s 文件前置 ASCII `"000000000"`（9 字节）作为反盗版混淆，让普通播放器直接拖进去会报错或静默漏读。strip 掉即可恢复标准 fMP4。**这和封面无关**，封面在独立的 `image.jpg` 文件里。

**进度反馈**：ffmpeg 启动时加 `-progress pipe:1 -nostats`，stdout 输出结构化 key=value（含 `out_time_ms`、`progress=end`），逐行解析后结合 `videoInfo.json` 的 `duration` 算百分比和 ETA，单行刷新进度条。

**封面嵌入**：默认从目录读取 `image.jpg`（回落 `group.jpg`），通过 `-map 2 -c copy -disposition:v:1 attached_pic` 作为第二个视频流嵌入。访达/Quick Look 缩略图会优先使用这张封面，开销通常 < 1MB。



## ⚠️ 合规与免责（请仔细阅读）

本工具**仅用于处理你已合法下载的、自己有权处理的内容**（例如你在 B 站客户端用自己的账号下载的视频，需要在本地长期保存或在自己的设备上播放）。

使用本工具时请遵守：

- **不要用于绕过 B 站付费/会员墙**。下载的清晰度必须是你账号有权访问的。
- **不要重新分发合并后的 mp4**。视频版权归原作者（UP 主 / B 站）所有，合并后的文件仅限个人本地使用。
- **不要商业化**。本项目仅提供本地文件处理功能，不涉及任何内容获取、解密、转播能力。
- **不要用于批量爬取**。本工具不会替你下载视频，假设输入文件已经合法存在于本地。

本工具的核心操作只是「strip m4s 的 9 字节头 → 用 ffmpeg 把视频流和音频流 mux 到 mp4 容器」，相当于一个本地文件格式转换器。所有版权与合规责任由使用者承担，作者不对滥用行为负责。

如版权方认为本工具不应存在，欢迎提 issue 讨论。



## License

[MIT License](LICENSE) - 本项目仅供学习和个人合法使用，不构成对任何版权内容的授权。
