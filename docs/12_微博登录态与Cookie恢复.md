# 微博登录态与 Cookie 恢复

适用于日常增量更新和官网微博原件补采。采集入口为 `weibo.com` 的官方作者帖子列表、长文及详情接口，账号为京城大师赛 `7525583841`。

## 浏览器已登录，为什么采集还会要求登录

浏览器中的登录态与 `.secrets/weibo.cookies.txt` 是两份状态。Cookie 文件是上一次导出的快照，不会随浏览器续期、重新登录而自动更新。因此浏览器仍然登录时，旧文件也可能已不能用于采集；这时重新导出即可，无需退出账号或重新扫码。

`login_required` 表示微博官网未认可采集请求携带的登录态，不能仅凭这个返回值断言账号已退出或某条 Cookie 必然到期。只有移动端登录态、文件中过期的 Cookie、服务器撤销会话等情况，都可能造成官网要求登录。Cookie 文件存在、导出条数大于零，也不能证明官网接口可用。

## 增量更新中的处理顺序

正常运行仍先复用已有 Cookie，不在每次增量更新时打开登录窗口：

```powershell
Set-Location D:\langrensha
.\.venv\Scripts\python.exe scripts/update_incremental.py --season S23 --yes
```

确认采集后，遇到 `login_required` 或 Cookie 无法加载的 `auth_configuration_failed`，入口按以下顺序恢复：

1. 保存失败窗口及已采原件，不把未完成窗口记为完成。
2. 调用 `login_session.py weibo --refresh`，打开项目已有的微博专用 Chrome 配置，访问 `https://weibo.com/`。
3. 先从该浏览器导出 Cookie，并请求与采集相同的官网帖子列表接口验证。浏览器已登录且验证通过时直接保存，不要求重新登录或按 Enter。
4. 官网仍要求登录时，提示用户在已打开的浏览器中完成登录或验证，然后回终端按 Enter；由当前窗口助手启动的会话，可在用户说明登录完成后由助手提交 Enter。
5. 新 Cookie 通过官网验证后，原子替换目标 Cookie 文件，重新创建采集会话，从失败的同一个日期窗口续采一次；后续未完成窗口接着执行。

每次增量命令最多启动一次登录态恢复。用户取消、关闭浏览器、验证未通过或续采仍失败时，保留未完成状态并说明具体原因，不反复弹窗或使用同一份失效 Cookie 无限重试。网络超时、限流和其他接口拒绝不直接当成 Cookie 失效，也不自动更换接口。

`--check-only` 不访问微博、不打开登录窗口、不写状态；显式 `--auth none` 保留匿名访问语义，不自动登录。采集前的确认规则不变，`--yes` 表示本次采集已经获准。

## 单独刷新与续跑

只更新微博 Cookie：

```powershell
.\.venv\Scripts\python.exe scripts/login_session.py weibo --refresh
```

默认复用 `.secrets/browser-profile-weibo-chrome/`，保存到 `.secrets/weibo.cookies.txt`。首次使用该浏览器配置时可能需要登录；以后浏览器仍有有效登录态时直接导出。Cookie 内容只留在本机，不写进日志、文档或 Git。

使用自定义 Cookie 路径时，刷新和采集指向同一个文件：

```powershell
.\.venv\Scripts\python.exe scripts/login_session.py weibo --refresh --cookies-file .secrets/weibo-other.cookies.txt
.\.venv\Scripts\python.exe scripts/update_incremental.py --season S23 --yes --weibo-cookies-file .secrets/weibo-other.cookies.txt
```

单独运行 `collect_weibo_archive.py` 不自动启动登录助手；先刷新 Cookie，再重跑原日期范围，程序会复用原件和未完成窗口：

```powershell
.\.venv\Scripts\python.exe scripts/login_session.py weibo --refresh
.\.venv\Scripts\python.exe scripts/collect_weibo_archive.py --since 2026-11-06 --until 2026-11-07
```

如果要复用平时使用、已经开启远程调试的 Chrome，可继续传入浏览器提供的本机 CDP 地址：

```powershell
.\.venv\Scripts\python.exe scripts/login_session.py weibo --cdp-url "替换为Chrome显示的完整本机CDP地址"
```

该入口只连接已有浏览器并导出，不新建或关闭用户的浏览器。微博 Cookie 同样先验证官网，再替换文件。

## 怎样判断恢复完成

- 登录助手报告官网帖子列表接口验证通过，新文件已保存；验证失败不覆盖旧 Cookie 文件。
- 原失败窗口已实际续采，列表扫描完成，长文、日期和图片满足现有完整性检查。
- `data/reports/S23/incremental/state.json` 中对应窗口的 `complete` 为 `true`，不再以 `login_required` 结束。

当天尚未结束时，“本次扫描完成”只表示已归档当前可见内容。次日仍按[增量覆盖规则](08_增量更新流程.md#第一步检查差距并确认采集)补扫尚未闭合的最后一天。

## 2026-11-07 本次恢复记录

本次打开微博专用浏览器时已有登录态。重新导出 10 条 Cookie 后，官网采集恢复正常；新增的 `--refresh` 入口也实测可直接导出并验证，无需再次登录或手动 Enter。

11月6日至7日窗口共归档4条帖子、15张图片；其中复用1条旧帖及其1张图，补采3条帖子和14张图片。扫描4页后完成，取得11月6日大师赛阵容公告 `5362279673496334`，长文及12张阵容图片齐全。此次采集没有写入对局数据库或发布网站。

实现见 [login_session.py](../scripts/login_session.py) 与 [update_incremental.py](../scripts/update_incremental.py)；本次回执见 [Cookie恢复与补采记录](../data/reports/S23/incremental/20261107_weibo_login_recovery.json)。
