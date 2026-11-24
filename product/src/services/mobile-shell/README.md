# 多源知识库 · Android 壳（R3）

Capacitor 壳工程，只负责「把云端知识库装进手机」。**壳里没有任何业务逻辑** ——
抓取、ASR、总结、存储、归档全部在服务端（`product/src/services/core`）。

本机没有 Android Studio / Android SDK / JDK / Gradle，所以**本工程未编译过**，
只做到「代码完整、引用完整、`npx cap sync` 通过」。首次编译请在装有 Android
Studio 的机器上完成。

---

## 一、四个能力与对应代码位置

| 能力 | 实现位置 |
|---|---|
| 打开后加载 `http://123.206.227.238:8080` | `capacitor.config.json` 的 `server.url` |
| Basic Auth 自动注入（不弹系统认证框） | `ShellWebViewClient.onReceivedHttpAuthRequest` |
| 接收系统分享 → POST 导入链接 | `ShareReceiverActivity` + `HttpPoster` |
| 内置 Web 页 + 读取 Cookie | `CookieWebActivity`（`CookieManager.getCookie`） |

关键文件（`android/app/src/main/java/com/catsk/multisourcekb/`）：

| 文件 | 作用 |
|---|---|
| `MainActivity.java` | Capacitor 主界面；换 WebViewClient、首次启动录入密码、响应壳内命令 |
| `ShellWebViewClient.java` | 在 Capacitor 默认 client 之上补 Basic Auth 应答 + 连接失败错误页 + `kb-shell://` 命令拦截 |
| `ShellPages.java` | 两张兜底页（连不上服务器 / 密码不对），纯内联 HTML，不依赖任何资源或网络 |
| `ShareReceiverActivity.java` | 系统分享进来时被拉起，抽出第一个链接并提交 |
| `HttpPoster.java` | `POST /api/v1/imports/link`（带 Basic Auth，20s 超时） |
| `CredentialStore.java` | 访问密码的本地存储（EncryptedSharedPreferences，见「密码存在哪」） |
| `CookieWebActivity.java` | 独立 WebView 登录页 + 读 Cookie |
| `ShellConfig.java` | 构建期常量（服务器地址、接口路径、默认用户名） |

资源：

| 文件 | 作用 |
|---|---|
| `res/xml/network_security_config.xml` | 只对 `123.206.227.238` 放开明文 HTTP |
| `AndroidManifest.xml` | `INTERNET` 权限、`networkSecurityConfig`、分享 `intent-filter`、两个 Activity |
| `res/layout/activity_share.xml` / `activity_cookie_web.xml` | 分享结果页 / 登录页布局 |

---

## 二、装完 Android Studio 后怎么编译

前提：安装 **Android Studio**（自带 JDK 与 Android SDK），首次启动让它装
**SDK Platform 36**（`compileSdk = 36`，见 `android/variables.gradle`）。

```bash
# 1. 在仓库根目录执行，生成原生依赖（node_modules 已被 .gitignore 忽略，需重新安装）
cd product/src/services/mobile-shell
npm install
npx cap sync
```

```text
# 2. 用 Android Studio 打开「android 子目录」，不是 mobile-shell 根目录
```

Android Studio → `File` → `Open` → 选择
`product/src/services/mobile-shell/android` → 等 Gradle Sync 完成。

```text
# 3. 连手机（打开「开发者选项 → USB 调试」），点顶部绿色 ▶ Run 'app'
```

只想要 APK 文件：

```text
Android Studio → Build → Build Bundle(s) / APK(s) → Build APK(s)
产物路径：
  product/src/services/mobile-shell/android/app/build/outputs/apk/debug/app-debug.apk
```

命令行等价（`JAVA_HOME` 指向 Android Studio 自带 JDK）：

```bash
cd product/src/services/mobile-shell/android
./gradlew assembleDebug      # Windows 用 gradlew.bat
```

> 首次 Gradle Sync 会下载 Gradle 发行包与依赖，需要联网，可能几分钟。

---

## 三、首次使用

1. 安装并打开「多源知识库」。
2. 弹出「设置访问密码」：
   - **用户名**默认 `kb`，一般不用改；
   - **访问密码**填服务器那道门禁的密码。
   - 密码**不在代码里**，只保存在本机（见「密码存在哪」）。
3. 填完点「保存」，壳会自动重新加载页面并通过认证。
4. 若密码填错：连续两次认证失败后会显示「访问密码不正确」页，点
   **重新输入密码** 即可重填，不用清应用数据。

**服务器地址不需要在手机上填** —— 它是构建期常量（见下节）。
`server.url` 写死意味着「装哪个 APK 就连哪台服务器」。

---

## 四、换 IP / 换服务器要改哪几个文件

**运行期不能改地址**，只能改完重新打包。共 **3 个文件**，缺一处就会出问题：

| 序号 | 文件 | 要改什么 | 漏改的后果 |
|---|---|---|---|
| 1 | `capacitor.config.json` | `server.url` 与 `allowNavigation` | WebView 仍开旧地址 |
| 2 | `android/app/src/main/java/com/catsk/multisourcekb/ShellConfig.java` | `SERVER_ORIGIN` | **分享导入会提交到旧服务器** |
| 3 | `android/app/src/main/res/xml/network_security_config.xml` | `<domain>` | 新地址被 Android 拦成明文请求失败（白屏 + 错误页） |

改完执行：

```bash
cd product/src/services/mobile-shell
npx cap sync          # 把 capacitor.config.json 同步进 android assets
# 然后 Android Studio 重新 Run / Build APK
```

> 如果新地址是 **https**，第 3 步可以不改（`base-config` 已禁止明文，
> https 本来就不需要放行）。

---

## 五、密码存在哪（安全取舍，必读）

用 `androidx.security:security-crypto` 的 **EncryptedSharedPreferences**，密钥由
Android Keystore 托管（AES256-GCM），密码以密文落在
`/data/data/com.catsk.multisourcekb/shared_prefs/kb_credentials.xml`。

**有意为之的降级路径**：若设备 Keystore 初始化失败（部分定制 ROM、恢复出厂后的
旧数据会出现），`CredentialStore` 会退到普通 `SharedPreferences`，此时密码**以明文**
存在 App 私有目录（仅 root 或同 uid 进程可读）。取舍理由写在
`CredentialStore.java` 的类注释里：宁可降级也不让整个壳打不开。若要更严格，
删掉该文件的 `catch` 分支即可。

已知副作用：一旦某次运行落到明文分支，之后即使 Keystore 恢复也读不到先前那份
密码（两个文件名不同），需要重新输入一次。

---

## 六、已知限制

1. **不能运行期改服务器地址。** `server.url` 是构建期配置。想在 App 内切换服务器
   需要自定义 Capacitor 插件调 `webView.loadUrl`，本轮明确不做。
2. **iOS 需要 Mac。** 本工程只生成了 `android/` 平台。要 iOS 需在 macOS 上
   `npm install @capacitor/ios && npx cap add ios`，并配 Xcode 签名。
3. **鸿蒙 NEXT 装不了 APK。** HarmonyOS NEXT 已移除 AOSP 兼容层，APK 无法安装；
   HarmonyOS 4.x 及更早（含安卓兼容）可以。
4. **Basic Auth 依赖反向代理下发 401。** 仓库里没有 Basic Auth 代码，密码门在
   nginx（`auth_basic`）一类代理上。若哪天换成表单登录，`onReceivedHttpAuthRequest`
   就不会被触发，需要改走表单流程。
5. **`minSdk = 24`**（Android 7.0）。更老的机器装不上。
6. **分享只处理 `text/plain` 的第一个链接。** 图片/文件分享不会进这个 App；
   多链接分享只取第一条。需要批量导入时用服务端的 `/api/v1/imports/links`。
7. **内置 Web 页会多出一个桌面图标。** 为了让「登录并读 Cookie」这个能力本轮就能在
   手机上验证，`CookieWebActivity` 挂了独立启动器入口（显示名「站点登录」）。
   不需要的话删掉 `AndroidManifest.xml` 里该 Activity 的 `MAIN/LAUNCHER`
   `intent-filter` 即可 —— 能力保留，只是没有入口。
8. **未编译验证。** 本机无 SDK/JDK，只做了 XML 良构性与 Java 结构检查。
   首次编译若报错属预期内的未知项。

---

## 七、本轮明确没做的事

- 没有把 Cookie 交给服务端（只做了「读取」这个能力，`setResult` 已留好返回通道）。
- 没有做运行期改地址、没有做设置页、没有做图标/启动图定制。
- 没有在壳里放任何业务逻辑。
