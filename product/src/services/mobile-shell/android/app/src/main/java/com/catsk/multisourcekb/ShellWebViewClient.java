package com.catsk.multisourcekb;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.webkit.HttpAuthHandler;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * 在 Capacitor 默认的 {@link BridgeWebViewClient} 之上补三件事，其它行为原样保留：
 *
 * <ol>
 *   <li><b>Basic Auth 自动应答</b>：站点密码门由反向代理下发
 *       {@code WWW-Authenticate: Basic}，系统默认会弹原生认证框；这里直接用本地
 *       保存的凭据 {@code handler.proceed(...)} 应答。</li>
 *   <li><b>连接失败错误页</b>：主文档加载失败（服务器不可达）时不再白屏，改为渲染
 *       {@link ShellPages#connectionErrorPage}，含当前地址与重试按钮。</li>
 *   <li><b>壳内命令拦截</b>：{@code kb-shell://} 开头的跳转被吞掉并回调宿主，
 *       用于错误页上的「重新输入密码」。</li>
 * </ol>
 */
public class ShellWebViewClient extends BridgeWebViewClient {

    /** 连续应答上限：密码错时若无限 proceed 会陷入 401 死循环。 */
    private static final int MAX_AUTH_ATTEMPTS = 2;

    /** 壳内命令回调，由 {@link MainActivity} 实现。 */
    public interface Host {
        /** 请求用户重新输入访问密码。 */
        void onPromptCredentialsRequested();
    }

    private final Context appContext;
    private final Host host;
    private int authAttempts = 0;

    public ShellWebViewClient(Bridge bridge, Context context, Host host) {
        super(bridge);
        this.appContext = context.getApplicationContext();
        this.host = host;
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        Uri uri = request.getUrl();
        if (uri == null) {
            return super.shouldOverrideUrlLoading(view, request);
        }
        if (handleShellCommand(uri.toString())) {
            return true;
        }
        if (isExternalSite(uri)) {
            return openExternally(uri);
        }
        return super.shouldOverrideUrlLoading(view, request);
    }

    @Override
    @SuppressWarnings("deprecation")
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        if (url != null && handleShellCommand(url)) {
            return true;
        }
        if (url != null) {
            Uri uri = Uri.parse(url);
            if (isExternalSite(uri)) {
                return openExternally(uri);
            }
        }
        // BridgeWebViewClient 只重写了 WebResourceRequest 版本，这里回落到
        // WebViewClient 的字符串版本（API < 24 的兼容路径）。
        return super.shouldOverrideUrlLoading(view, url);
    }

    /**
     * 是否是产品自身域名之外的 http(s) 站点。
     *
     * <p>B 站 / 知乎 / 小红书的链接一律不在壳内加载：它们在 WebView 里不能登录、
     * 播放器多半不可用，而且会把产品页整体顶掉，返回键一按就退出 App。
     */
    private boolean isExternalSite(Uri uri) {
        String scheme = uri.getScheme();
        if (scheme == null) {
            return false;
        }
        boolean isWeb = "http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme);
        if (!isWeb) {
            return false;
        }
        String productHost = Uri.parse(ShellConfig.SERVER_ORIGIN).getHost();
        String targetHost = uri.getHost();
        if (targetHost == null) {
            return false;
        }
        return productHost == null || !targetHost.equalsIgnoreCase(productHost);
    }

    /**
     * 交给系统打开（B 站 App 优先，装不上就落浏览器）。
     *
     * @return true 表示已接管。没有可处理的应用时返回 false，交回 WebView 兜底，
     *         避免用户点了没反应。
     */
    private boolean openExternally(Uri uri) {
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, uri);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            appContext.startActivity(intent);
            return true;
        } catch (Exception error) {
            return false;
        }
    }

    @Override
    public void onReceivedHttpAuthRequest(
            WebView view,
            HttpAuthHandler handler,
            String host,
            String realm) {
        String username = CredentialStore.getUsername(appContext);
        String password = CredentialStore.getPassword(appContext);
        boolean hasCredentials = password != null && !password.isEmpty();

        if (hasCredentials && authAttempts < MAX_AUTH_ATTEMPTS) {
            authAttempts++;
            handler.proceed(username, password);
            return;
        }

        // 没有凭据，或已连续失败：取消掉，避免系统认证框反复弹出。
        handler.cancel();
        final WebView target = view;
        view.post(new Runnable() {
            @Override
            public void run() {
                target.loadDataWithBaseURL(
                        null,
                        ShellPages.authErrorPage(target.getUrl()),
                        "text/html",
                        "UTF-8",
                        null);
            }
        });
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        super.onReceivedError(view, request, error);
        // 只有主文档失败才替换页面；子资源（图片 / 脚本）失败不打断阅读。
        if (request != null && request.isForMainFrame()) {
            String failedUrl = request.getUrl() == null ? "" : request.getUrl().toString();
            String reason = error == null || error.getDescription() == null
                    ? "无法连接"
                    : error.getDescription().toString();
            showConnectionError(view, failedUrl, reason);
        }
    }

    /**
     * 页面成功加载后重置计数，避免用户正常浏览一段时间后因历史失败次数被锁死。
     */
    @Override
    public void onPageFinished(WebView view, String url) {
        super.onPageFinished(view, url);
        if (url != null && !url.startsWith("data:")) {
            authAttempts = 0;
        }
    }

    private void showConnectionError(WebView view, String failedUrl, String reason) {
        view.loadDataWithBaseURL(
                null,
                ShellPages.connectionErrorPage(failedUrl, reason),
                "text/html",
                "UTF-8",
                null);
    }

    private boolean handleShellCommand(String url) {
        if (url == null || !url.startsWith(ShellConfig.SHELL_SCHEME)) {
            return false;
        }
        if (url.startsWith(ShellConfig.COMMAND_PROMPT_CREDENTIALS) && host != null) {
            host.onPromptCredentialsRequested();
        }
        return true;
    }
}
