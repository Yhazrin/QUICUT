# FFmpeg 命令策略草案

## 1) 按切点生成分段

给定切点数组：`[t1, t2, t3 ...]`，转换为区间：

- `[0, t1]`
- `[t1, t2]`
- `[t2, t3]`
- `[t3, end]`

## 2) 极速无损（copy）模板

```bash
ffmpeg -ss {start} -to {end} -i input.mp4 -c copy -map 0 output_{index}.mp4
```

说明：
- 速度快、画质无损。
- 切点可能按关键帧对齐，非逐帧精确。

## 3) 精准高质（重编码）模板

```bash
ffmpeg -ss {start} -to {end} -i input.mp4 \
  -c:v libx264 -preset slow -crf 16 \
  -c:a aac -b:a 192k \
  output_{index}.mp4
```

说明：
- 切点精确度高。
- 会重编码，耗时增加。

## 4) 进度回传建议

可通过 `-progress pipe:1 -nostats` 解析：

- `out_time_ms`
- `speed`
- `progress=continue/end`

## 5) 错误处理建议

- 输入文件不可读：提前做路径检测
- 容器/编码不兼容：自动回退到重编码策略
- 输出目录无权限：导出前写入测试文件

## 6) 命名规则建议

- 默认：`{原文件名}_{序号3位}.mp4`
- 例：`lecture_001.mp4`
