# Markdown 预览依赖

管理面板随应用打包以下浏览器库，无需在运行时连接 CDN：

| 库 | 版本 | 来源 | 许可证 |
| --- | --- | --- | --- |
| Marked | 18.1.1 | [Marked 官方仓库](https://github.com/markedjs/marked) | [MIT](../dashboard_static/licenses/marked.txt) |
| DOMPurify | 3.4.17 | [DOMPurify 官方仓库](https://github.com/cure53/DOMPurify) | [Apache-2.0 或 MPL-2.0](../dashboard_static/licenses/dompurify.txt) |

资源来自对应固定版本的 npm 包：Marked 的 `lib/marked.umd.js` 和 DOMPurify 的 `dist/purify.min.js`。文件分别保存为 `dashboard_static/markdown_marked.js` 和 `dashboard_static/markdown_purify.js`；更新时一起更新版本记录及许可证。

Markdown 解析后必须经过 DOMPurify 的标签和属性白名单。原始 HTML 与图片只显示文本，预览不执行代码或加载图片。源文本的保存与出站处理独立于渲染。
