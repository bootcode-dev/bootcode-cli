# bootcode CLI

[bootcode](https://bootcode.cn/) 的本地命令行提交工具。部分课程的关卡需要用它拉取题目、本地跑测试、提交结果。

## 安装

需要 Python 3.11+。

```bash
pip install "bootcode-cli @ git+https://github.com/bootcode-dev/bootcode-cli.git"
```

装完后确认能跑：

```bash
bootcode --version
```

## 登录

```bash
bootcode login
```

会打开浏览器，登录并确认授权后命令行会自动完成登录，凭证保存在本机
`~/.config/bootcode/config.toml`。之后可以用 `bootcode status` 随时查看当前登录的账号。

## 使用流程

每道题拉取到当前目录，可以在同一个目录里连续拉取多道题：

```bash
bootcode pull <course-slug>/<stage-slug>   # 写入起始代码 + 测试文件到当前目录

bootcode run                                # 本地跑公开测试，纯本地断言，不联网
bootcode submit                             # 本地跑评分函数，收集结果后一次性提交，返回逐条 correct/incorrect
```

`bootcode run` 只是帮你自查实现是否正确，不联网、不计分；只有 `bootcode submit`
才会把结果发给服务器判分。判定失败可以改完代码后随时重新 `bootcode submit`，不扣分。

## 常用命令

| 命令                               | 作用                                          |
| ---------------------------------- | --------------------------------------------- |
| `bootcode login`                   | 登录                                          |
| `bootcode status`                  | 查看当前登录账号                              |
| `bootcode logout`                  | 清除本机保存的登录凭证                        |
| `bootcode pull <course>/<stage>`   | 拉取一道题到当前目录                          |
| `bootcode run`                     | 本地跑该题的公开测试（不联网）                |
| `bootcode submit`                  | 提交评分（联网，一次性提交）                  |
| `bootcode submit --debug`          | 提交时额外把请求/响应写入本地调试文件         |
| `bootcode configure <key> <value>` | 修改本地配置，如切到自建/本地部署的 `api_url` |
