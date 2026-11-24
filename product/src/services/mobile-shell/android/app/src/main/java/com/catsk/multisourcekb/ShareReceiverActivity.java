package com.catsk.multisourcekb;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import java.util.Locale;

/**
 * 系统分享接收器。
 *
 * <p>用原生 Activity + {@code intent-filter}（{@code ACTION_SEND} / {@code text/plain}），
 * 而不是 Capacitor 插件：从 B 站 / 知乎 / 小红书分享过来时，本 App 的进程和 WebView
 * 可能都还没启动，插件模型要求 WebView 已就绪，做不到。
 *
 * <p>职责只有一个：从分享文本里抽出第一个链接，POST 到服务端
 * {@code /api/v1/imports/link}，然后把结果告诉用户。抓取、总结、入库全在服务端。
 *
 * <p>界面是三态的浮层弹窗，<b>不自动关闭</b>：
 * <ol>
 *   <li>保存中：进度条 + 链接，按钮全部隐藏。</li>
 *   <li>已加入队列：显示结果 + 两个出口（留在产品 / 返回来源应用）。</li>
 *   <li>失败：显示原因 + 只有一个「关闭」。</li>
 * </ol>
 */
public class ShareReceiverActivity extends AppCompatActivity {

    /** 分享文本里常见「标题 + 链接 + 复制此链接打开」混排，取第一个 http(s) 片段。 */
    private static final String URL_PATTERN = "https?://[^\\s\"'<>]+";

    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private TextView statusView;
    private ProgressBar progressView;
    private Button stayButton;
    private Button backButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_share);

        applyDialogWindow();

        statusView = findViewById(R.id.share_status);
        progressView = findViewById(R.id.share_progress);
        stayButton = findViewById(R.id.share_stay);
        backButton = findViewById(R.id.share_close);

        stayButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                openProduct();
            }
        });
        backButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                finish();
            }
        });

        final String sharedUrl = extractFirstUrl(readSharedText(getIntent()));
        backButton.setText(backLabelFor(sharedUrl));

        if (sharedUrl == null) {
            showFailure("分享内容里没有找到链接");
            return;
        }

        showSubmitting(sharedUrl);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final HttpPoster.Result result = HttpPoster.postImportLink(
                        ShareReceiverActivity.this, sharedUrl);
                mainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (isFinishing()) {
                            return;
                        }
                        if (result.success) {
                            showSuccess(result.message);
                        } else {
                            showFailure(result.message);
                        }
                    }
                });
            }
        }, "share-import").start();
    }

    /** 浮层宽度：屏幕的 86%，高度随内容。窗口背景交给卡片自己画圆角。 */
    private void applyDialogWindow() {
        Window window = getWindow();
        if (window == null) {
            return;
        }
        window.setBackgroundDrawableResource(android.R.color.transparent);
        int width = (int) (getResources().getDisplayMetrics().widthPixels * 0.86f);
        window.setLayout(width, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private void showSubmitting(String url) {
        statusView.setText(getString(R.string.share_state_submitting) + "\n" + url);
        progressView.setVisibility(View.VISIBLE);
        stayButton.setVisibility(View.GONE);
        backButton.setVisibility(View.GONE);
    }

    private void showSuccess(String message) {
        statusView.setText("已加入队列\n" + message);
        progressView.setVisibility(View.GONE);
        stayButton.setVisibility(View.VISIBLE);
        backButton.setVisibility(View.VISIBLE);
    }

    private void showFailure(String message) {
        statusView.setText("导入失败\n" + message);
        progressView.setVisibility(View.GONE);
        stayButton.setVisibility(View.GONE);

        // 失败时只剩一个按钮，去掉左边距让它占满整行。
        LinearLayout.LayoutParams params = (LinearLayout.LayoutParams) backButton.getLayoutParams();
        params.setMarginStart(0);
        backButton.setLayoutParams(params);

        backButton.setText(R.string.share_action_close);
        backButton.setVisibility(View.VISIBLE);
    }

    /** 「留在产品」：拉起主界面并结束弹窗。 */
    private void openProduct() {
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(intent);
        finish();
    }

    /**
     * 按分享来源决定第二个按钮叫什么。
     *
     * <p>只认三个已知平台的域名，其余一律「返回原应用」——按钮点击的本质都是
     * {@code finish()}，回到发起分享的那一屏。
     */
    private String backLabelFor(String url) {
        if (url == null) {
            return getString(R.string.share_action_back);
        }
        String host = Uri.parse(url).getHost();
        if (host == null) {
            return getString(R.string.share_action_back);
        }
        host = host.toLowerCase(Locale.ROOT);
        if (host.endsWith("bilibili.com") || host.endsWith("b23.tv")) {
            return "返回B站";
        }
        if (host.endsWith("zhihu.com")) {
            return "返回知乎";
        }
        if (host.endsWith("xiaohongshu.com") || host.endsWith("xhslink.com")) {
            return "返回小红书";
        }
        return getString(R.string.share_action_back);
    }

    /** 从 ACTION_SEND 的 extra 或 ClipData 里取出分享正文。 */
    private String readSharedText(Intent intent) {
        if (intent == null) {
            return null;
        }
        CharSequence text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
        if (text != null && text.length() > 0) {
            return text.toString();
        }
        if (intent.getClipData() != null && intent.getClipData().getItemCount() > 0) {
            CharSequence clipped = intent.getClipData().getItemAt(0).getText();
            if (clipped != null && clipped.length() > 0) {
                return clipped.toString();
            }
        }
        return null;
    }

    private String extractFirstUrl(String text) {
        if (text == null) {
            return null;
        }
        java.util.regex.Matcher matcher =
                java.util.regex.Pattern.compile(URL_PATTERN).matcher(text);
        if (!matcher.find()) {
            return null;
        }
        return trimTrailingPunctuation(matcher.group());
    }

    /** 分享文本里链接常被中文标点包住，去掉尾部的标点。 */
    private String trimTrailingPunctuation(String url) {
        String trimmed = url;
        while (trimmed.length() > 0) {
            char last = trimmed.charAt(trimmed.length() - 1);
            if (last == '.' || last == ',' || last == ')' || last == '）' || last == '。'
                    || last == '，' || last == ';' || last == '；' || last == '!'
                    || last == '！' || last == '、' || last == '》' || last == '」') {
                trimmed = trimmed.substring(0, trimmed.length() - 1);
                continue;
            }
            break;
        }
        return trimmed.isEmpty() ? null : trimmed;
    }
}
