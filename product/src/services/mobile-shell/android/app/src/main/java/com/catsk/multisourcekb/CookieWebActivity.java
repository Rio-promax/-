package com.catsk.multisourcekb;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;

/**
 * 内置 Web 页：独立 WebView 打开指定站点，供用户登录，并读取该站点的 Cookie。
 *
 * <p>用途是把 B 站这类需要登录态的站点的 Cookie 取出来（本轮先把能力做出来，
 * 后续再交给服务端，壳里不做任何业务处理）。
 *
 * <p>可通过 {@code EXTRA_URL} 指定要打开的地址；不传则用
 * {@link ShellConfig#DEFAULT_COOKIE_LOGIN_URL}。
 *
 * <p>读取结果：显示在页面底部、复制到剪贴板，并在以
 * {@code startActivityForResult} 启动时通过 {@code EXTRA_COOKIE} 返回。
 */
public class CookieWebActivity extends AppCompatActivity {

    public static final String EXTRA_URL = "extra_url";
    public static final String EXTRA_COOKIE = "extra_cookie";

    private WebView webView;
    private TextView cookieView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_cookie_web);

        webView = findViewById(R.id.cookie_webview);
        cookieView = findViewById(R.id.cookie_value);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        // B 站等站点依赖 localStorage 与第三方 Cookie 才能完成登录。
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, true);

        Button readButton = findViewById(R.id.cookie_read);
        readButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                readCookie();
            }
        });

        Button closeButton = findViewById(R.id.cookie_close);
        closeButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                finish();
            }
        });

        webView.loadUrl(resolveTargetUrl(getIntent()));
    }

    private String resolveTargetUrl(Intent intent) {
        if (intent != null) {
            String override = intent.getStringExtra(EXTRA_URL);
            if (override != null && !override.trim().isEmpty()) {
                return override.trim();
            }
        }
        return ShellConfig.DEFAULT_COOKIE_LOGIN_URL;
    }

    /**
     * 读取当前页面站点的 Cookie。
     *
     * <p>注意：{@link CookieManager#getCookie} 返回的是该 URL 作用域下可用的
     * {@code name=value; name2=value2} 串；第三方 Cookie 不一定全在其中，
     * 因此这里读的是「当前页面 URL」而不是站点根域。
     */
    private void readCookie() {
        String currentUrl = webView.getUrl();
        if (currentUrl == null || currentUrl.startsWith("data:")) {
            Toast.makeText(this, "页面还没有加载完成", Toast.LENGTH_SHORT).show();
            return;
        }

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.flush();
        String cookie = cookieManager.getCookie(currentUrl);
        if (cookie == null || cookie.trim().isEmpty()) {
            cookieView.setText("未读取到 Cookie：" + currentUrl + "\n请先在该页面完成登录。");
            return;
        }

        cookieView.setText(cookie);
        ClipboardManager clipboard =
                (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(ClipData.newPlainText("cookie", cookie));
        }
        Toast.makeText(this, "已读取并复制 Cookie", Toast.LENGTH_SHORT).show();

        Intent result = new Intent();
        result.putExtra(EXTRA_COOKIE, cookie);
        setResult(RESULT_OK, result);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }
}
