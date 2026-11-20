# 本机元数据导入与生产切换

公开仓库及便携包均不包含元数据。可以从任意本机可读目录导入；工作台没有在线连接 Qlik、SQL 或 AWS 的步骤。

## 导出格式

需要通过已有 Qlik 元数据导出流程获取解包后的文本文件，保持 JSON 属性结构。该产品不负责从 Qlik Server 下载或解包 `.qvf`。

```text
apps/
  Stream Alpha/
    Application A/
      app-properties.json
      script.qvs
      variables.json
      dimensions.json
      measures.json
      objects/
        sheet.json
  Stream Beta/
    Application B/
      ...
```

- `app-properties.json`：应用标题等属性，可包含 `qStream` 信息。
- `script.qvs`：完整 SQL / Qlik LOAD 脚本。缺失时无法形成完整脚本血缘。
- `objects/`：Sheet 及图表对象的 JSON 定义（包含属性和子对象）。缺失时可能只有技术字段而没有 Sheet 字段。
- `variables.json`、`dimensions.json`、`measures.json`：使用变量和主维度/度量时需要。

扫描以存在 `app-properties.json` 或 `script.qvs` 的目录作为 App 边界。能被识别不代表内容完整；请核对 Sheet 和字段数量及缺失提示。支持 `apps/App/` 平铺目录、单个 App 目录，以及外层再包一层 `apps/`。同名 App 在不同 Stream 中分别保留。

Stream 名称优先使用导出属性中的 Stream 信息，否则使用 App 的上一级目录名称。平铺导出且属性没有 Stream 时显示「未标注 Stream」。不要把 App 内文件额外拆入新目录。

## 切换生产环境

把生产导出放在独立的本机目录，例如 `D:\QlikExports\production-YYYYMMDD\apps`。打开左下角「元数据目录」，输入完整根目录，点击「扫描并导入」。确认三个 Stream（或本次导出的实际数量）、App 总数、导入错误和代表字段的源表代码。

导入是完整替换分析快照，不会把测试和生产数据合并。源导出文件保持原样，工作台不向其写入解析结果。导入失败时保留原快照；部分 App 失败时显示失败清单，并提供成功 App 的分析。

更换目录后，旧页面的过期快照请求会被拒绝，请等待界面完成更新。修改磁盘上的导出后需要再次扫描。界面选中的外部目录不持久保存；重启时使用 `-MetadataRoot`，重新选择目录，或把文件放到本机 `metadata/apps` 下。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 目录不存在 | 确认是运行服务那台电脑上的完整路径，已解压 ZIP，并有读取权限 |
| 找不到 App | 确认根目录下确有 `app-properties.json` 或 `script.qvs`，而不是只有 `.qvf` |
| Stream 名称不符 | 检查 App 属性中的 Stream 信息及上级目录；属性值优先 |
| 缺少 Sheet 或字段 | 补齐 `objects/` 下的 Sheet、图表与子对象定义 |
| 表达式或来源未解析 | 补齐变量、主度量/维度、外部 Include 和所需 schema；动态逻辑需要人工复核 |
| 刷新仍是旧结果 | 重新扫描目录；浏览器刷新只读取当前分析快照 |

## 公开分享

`metadata/` 的数据被 Git 忽略，但仍应把实际导出放在仓库外。发布工具使用源码白名单，并拒绝仓库内出现元数据载荷。不要上传个人使用后的整目录、内部便携包、带业务代码的报告或截图。公开版应通过[发布流程](./releasing.md)重新构建。
