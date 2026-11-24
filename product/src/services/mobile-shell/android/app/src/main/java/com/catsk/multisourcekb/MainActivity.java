package com.catsk.multisourcekb;

import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AlertDialog;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeActivity;

/**
 * 壳的主界面：Capacitor 的 WebView 加载云端知识库。
 *
 * <p>本类只做四件事，业务逻辑全部在服务端：
 * <ol>
 *   <li>把 Capacitor 默认的 WebViewClient 换成 {@link ShellWebViewClient}
 *       （自动应答 Basic Auth + 错误页 + 外链出壳）。</li>
 *   <li>首次启动时让用户录入访问密码；密码不写进源码。</li>
 *   <li>响应壳内命令（错误页上的「重新输入密码」）。</li>
 *   <li>接管返回键：先在产品内部逐级回退，退无可退时二次确认再退出。</li>
 * </ol>
 *
 * <p><b>运行期不能改服务器地址</b>：{@code server.url} 是构建期配置，
 * 换 IP / 换服务器必须重新打包（见 README「已知限制」）。
 */
public class MainActivity extends BridgeActivity implements ShellWebViewClient.Host {

    /** 根视图下按返回的要求：这个时间窗内再按一次才真正退出。 */
    private static final long EXIT_CONFIRM_WINDOW_MS = 2000L;

    private long lastBackPressAt = 0L;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Capacitor 8 的 BridgeActivity 没有重写 onBackPressed，不接管的话
        // 任何页面按返回都会直接 finish()，连设置页都退不出来。
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                handleBack();
            }
        });

        if (!CredentialStore.hasPassword(this)) {
            promptForCredentials(false);
        }
    }

    /**
     * 在 Capacitor 完成 Bridge 创建后立刻换掉 WebViewClient。
     *
     * <p>必须放在 {@code load()} 里而不是 {@code onCreate()} 末段：默认 client 在
     * {@code super.load()} 期间就已经发起首屏请求，如果服务器在这次请求上抛出 401，
     * 来不及换 client 就会弹出系统原生认证框。这里换完再 reload，保证认证质询
     * 一定落到 {@link ShellWebViewClient#onReceivedHttpAuthRequest}。
     */
    @Override
    protected void load() {
        super.load();

        Bridge bridge = getBridge();
        if (bridge == null) {
            return;
        }
        bridge.setWebViewClient(new ShellWebViewClient(bridge, this, this));

        android.webkit.WebView webView = bridge.getWebView();
        if (webView != null) {
            // 取消默认 client 发起的那次未应答请求，用新 client 重新开始。
            webView.reload();
        }
    }

    @Override
    public void onPromptCredentialsRequested() {
        promptForCredentials(true);
    }

    /**
     * 返回键：先问前端能否在产品内部回退一级，退无可退时才走退出确认。
     *
     * <p>前端 {@code window.__kbBack()} 返回 {@code "handled"} 表示已回退，
     * 返回 {@code "root"} 表示当前已在根视图。脚本异常或 WebView 未就绪时按
     * 根视图处理，避免用户被卡在一个退不出的页面上。
     */
    private void handleBack() {
        Bridge bridge = getBridge();
        WebView webView = bridge == null ? null : bridge.getWebView();
        if (webView == null) {
            confirmExit();
            return;
        }
        webView.evaluateJavascript(
                "(function(){try{return (window.__kbBack && window.__kbBack()) || 'root';}"
                        + "catch(e){return 'root';}})()",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (value != null && value.contains("handled")) {
                            return;
                        }
                        confirmExit();
                    }
                });
    }

    private void confirmExit() {
        long now = System.currentTimeMillis();
        if (now - lastBackPressAt <= EXIT_CONFIRM_WINDOW_MS) {
            finish();
            return;
        }
        lastBackPressAt = now;
        Toast.makeText(this, "再按一次退出", Toast.LENGTH_SHORT).show();
    }

    /**
     * 让用户录入用户名与密码。
     *
     * @param reenter true 表示由「密码错误」触发的重填。
     */
    private void promptForCredentials(final boolean reenter) {
        float density = getResources().getDisplayMetrics().density;
        int padding = (int) (20 * density);

        LinearLayout container = new LinearLayout(this);
        container.setOrientation(LinearLayout.VERTICAL);
        container.setPadding(padding, padding / 2, padding, 0);

        final EditText usernameInput = new EditText(this);
        usernameInput.setHint("用户名");
        usernameInput.setSingleLine(true);
        usernameInput.setInputType(InputType.TYPE_CLASS_TEXT);
        usernameInput.setText(CredentialStore.getUsername(this));
        container.addView(
                usernameInput,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        final EditText passwordInput = new EditText(this);
        passwordInput.setHint("访问密码");
        passwordInput.setSingleLine(true);
        passwordInput.setInputType(
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        container.addView(
                passwordInput,
                new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));

        final AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(reenter ? "重新输入访问密码" : "设置访问密码")
                .setMessage("密码只保存在本机，用于自动通过服务器的登录验证；不会上传，也不会写进代码。")
                .setView(container)
                .setPositiveButton("保存", null)
                .setNegativeButton("稍后", null)
                .create();

        dialog.show();

        // show() 之后再挂监听，才能在密码为空时阻止对话框关闭。
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                String password = passwordInput.getText().toString();
                if (password.isEmpty()) {
                    Toast.makeText(MainActivity.this, "请输入访问密码", Toast.LENGTH_SHORT).show();
                    return;
                }
                CredentialStore.save(
                        MainActivity.this,
                        usernameInput.getText().toString(),
                        password);
                dialog.dismiss();
                reloadWebView();
            }
        });
    }

    private void reloadWebView() {
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            return;
        }
        bridge.getWebView().reload();
    }
}
