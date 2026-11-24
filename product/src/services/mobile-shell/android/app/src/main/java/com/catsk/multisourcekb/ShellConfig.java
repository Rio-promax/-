package com.catsk.multisourcekb;

/**
 * 构建期常量集中处。
 *
 * <p>注意：WebView 的<b>首屏地址</b>由 {@code capacitor.config.json} 的
 * {@code server.url} 决定，不读本文件。本文件的 {@link #SERVER_ORIGIN} 只用于
 * 分享导入的 API 调用与错误页展示，因此两处必须保持一致。
 *
 * <p><b>换服务器 / 换 IP 需要同时改三个地方</b>（运行期无法改，只能重新打包）：
 * <ol>
 *   <li>{@code capacitor.config.json} 的 {@code server.url}</li>
 *   <li>本文件的 {@link #SERVER_ORIGIN}</li>
 *   <li>{@code res/xml/network_security_config.xml} 里的 domain</li>
 * </ol>
 */
final class ShellConfig {

    /** 知识库服务器地址。必须与 capacitor.config.json 的 server.url 一致。 */
    static final String SERVER_ORIGIN = "http://123.206.227.238:8080";

    /** 分享链接导入接口，见服务端 POST /api/v1/imports/link。 */
    static final String IMPORT_LINK_ENDPOINT = SERVER_ORIGIN + "/api/v1/imports/link";

    /** Basic Auth 默认用户名；密码不入代码，由用户首次启动时输入。 */
    static final String DEFAULT_USERNAME = "kb";

    /** 内置 Web 页的默认地址，用于登录并读取 Cookie（B 站登录态）。 */
    static final String DEFAULT_COOKIE_LOGIN_URL = "https://www.bilibili.com";

    /** 自定义 scheme，供壳自己的页面回跳原生动作，避免对外暴露 JS bridge。 */
    static final String SHELL_SCHEME = "kb-shell://";

    /** 要求重新输入访问密码的内部命令。 */
    static final String COMMAND_PROMPT_CREDENTIALS = "kb-shell://prompt-credentials";

    static final int HTTP_CONNECT_TIMEOUT_MS = 15000;
    static final int HTTP_READ_TIMEOUT_MS = 20000;

    private ShellConfig() {
        // 纯常量持有类，不实例化。
    }
}
