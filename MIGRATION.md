# BinTextly — 站点维护

纯静态站，页面本身就是部署产物。没有 dist 目录，没有打包器，没有运行时依赖。

## 唯一变量

`site.config.js` 里只有一个变量：

```js
const SITE_ORIGIN = "https://bintextly.com";
```

canonical、`robots.txt`、`sitemap.xml` 的绝对地址全部由它生成，页面内不硬编码域名。改域名 = 改这一行 + 跑一次构建。

## 构建与校验

```bash
python3 build.py           # 写 canonical / robots.txt / sitemap.xml
python3 build.py --check   # 只读校验，有问题退出码 1
```

构建是幂等的，重复跑不产生额外改动。提交前跑 `--check`。

## build.py 校验什么

- 每个页面恰好 1 条 canonical，值 = `SITE_ORIGIN` + 页面路径（带尾斜杠）
- 所有绝对网址必须落在 `SITE_ORIGIN` 上；白名单只有 `www.w3.org`（SVG 命名空间）、`www.sitemaps.org`、`schema.org`。任何其他主机（包括旧域名）直接报错
- 所有内部 `<a href>` 必须指向磁盘上真实存在的文件；绝对链接必须留在 `SITE_ORIGIN` 上
- `sitemap.xml` 的 `<loc>` 集合 = 实际页面集合，无重复，`lastmod` 为 `YYYY-MM-DD`
- `robots.txt` 与生成结果逐字节一致，且不封禁抓取
- 页面必须有 title / meta description / 唯一 h1，且无 noindex、无 meta keywords
- `404.html` 不得声明 canonical，但链接必须可解析

## 加一个页面

1. 新建 `<slug>/index.html`，写好正文与 TDK
2. `python3 build.py` —— 页面由文件系统自动发现，canonical、sitemap 自动补齐
3. 在相关页面的 Related converters 区块加内链（锚文本描述性 + 一句 15 词以内说明）
4. `python3 build.py --check`

页面列表不落在配置里，避免「加了页面忘了登记」这类漂移。

## 不对外发布的文件

`.assetsignore` 把构建脚本、配置、文档、`tools/` 排除在 Workers 静态资源之外，仓库里保留、线上不可访问。

## 404 页面

`404.html` 在仓库根部，带 `noindex`、不带 canonical，大小约 2.3 KB。但文件存在不等于会被使用：Workers 静态资源默认的 `not_found_handling` 是 `none`，未匹配路径返回 **404 + 空响应体**，而 `/404.html` 本身会被 307 到 `/404`。

要让任意无效路径返回这张页面，需把未匹配路径处理设为 `404-page`：

```jsonc
// wrangler.jsonc
{
  "name": "<Worker 名，必须与现有 Worker 一致>",
  "compatibility_date": "2026-11-01",
  "assets": {
    "directory": ".",
    "not_found_handling": "404-page"
  }
}
```

或在 Cloudflare 控制台：Workers → 该项目 → Settings → 静态资源/Build → Not found handling → 选 `404 page`。

仓库根的 `wrangler.jsonc` 已写入上述配置：`name` 为 `bintextly`，`directory` 指仓库根（本站无构建产物），`not_found_handling` 为 `404-page`。改动该文件等同改线上行为；若 `name` 与线上 Worker 不一致，会部署到另一个 Worker，自定义域名不会跟过去。

