# Python 依赖

网站的页面由 `website/web` 内的 Next.js 提供，Python 只做最终 JSON 的统计、导出及照片处理，不再运行 FastAPI 或连接 PostgreSQL。

| 文件 | 用途 |
| --- | --- |
| `web.txt` | 本地静态数据导出与照片处理，Python 3.12 |
| `collection.txt` | 官方媒体采集、登录态导出和显式音频校验，Python 3.12 |
| `test.txt` | 上述功能及规则、统计测试，Python 3.12 |
| `funasr.txt` | 主 Paraformer 转写，单独的 Python 3.9 环境 |

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/test.txt
```

仅采接口资料时可只安装 `requests`。前端在 `website/web` 执行 `npm ci`。主转写使用 `.venv-funasr39`，不要和 Python 3.12 依赖混装。历史赛季 OCR、第二模型复听、模型横评及数据库依赖已退役。
