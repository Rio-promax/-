package com.catsk.multisourcekb;

/**
 * 壳自带的两张兜底页面（连不上服务器 / 访问密码不正确）。
 *
 * <p>用 {@code loadDataWithBaseURL(null, ...)} 直接渲染，避免依赖任何本地资源文件
 * 或服务端可达性——服务器不可达时正是要用它。
 *
 * <p>「重新输入密码」按钮跳到 {@link ShellConfig#COMMAND_PROMPT_CREDENTIALS}，
 * 由 {@link ShellWebViewClient} 拦截并回调宿主，<b>不向页面暴露任何 JS 接口</b>，
 * 避免远程页面（知识库自身）也能调用原生能力。
 */
final class ShellPages {

    private ShellPages() {
        // 纯静态工具类。
    }

    /** 连不上服务器时的错误页：显示当前地址 + 重试。 */
    static String connectionErrorPage(String failedUrl, String reason) {
        String safeUrl = escapeHtml(failedUrl);
        String safeReason = escapeHtml(reason);
        String retryTarget = escapeJsString(failedUrl);
        return wrap(
                "无法连接服务器",
                "<p class=\"hint\">请确认手机已联网，且服务器正在运行。</p>"
                        + "<dl><dt>当前地址</dt><dd class=\"mono\">" + safeUrl + "</dd>"
                        + "<dt>错误</dt><dd class=\"mono\">" + safeReason + "</dd></dl>"
                        + "<button id=\"retry\" type=\"button\">重试</button>",
                "document.getElementById('retry').addEventListener('click',function(){"
                        + "location.replace('" + retryTarget + "');});");
    }

    /** 密码不对或未录入时的提示页：说明 + 重试 + 重新输入密码。 */
    static String authErrorPage(String failedUrl) {
        String safeUrl = escapeHtml(failedUrl);
        String retryTarget = escapeJsString(failedUrl);
        String promptCommand = escapeJsString(ShellConfig.COMMAND_PROMPT_CREDENTIALS);
        return wrap(
                "访问密码不正确",
                "<p class=\"hint\">服务器返回 401。若刚改过密码，请重新输入后再试。</p>"
                        + "<dl><dt>当前地址</dt><dd class=\"mono\">" + safeUrl + "</dd></dl>"
                        + "<button id=\"retry\" type=\"button\">重试</button>"
                        + "<button id=\"reenter\" class=\"secondary\" type=\"button\">重新输入密码</button>",
                "document.getElementById('retry').addEventListener('click',function(){"
                        + "location.replace('" + retryTarget + "');});"
                        + "document.getElementById('reenter').addEventListener('click',function(){"
                        + "location.href='" + promptCommand + "';});");
    }

    private static String wrap(String title, String bodyHtml, String script) {
        return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
                + "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
                + "<title>" + escapeHtml(title) + "</title><style>"
                + "html,body{margin:0;padding:0;background:#f7f7f5;color:#26292b;"
                + "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif;}"
                + "main{max-width:520px;margin:0 auto;padding:28px 20px 40px;}"
                + "h1{font-size:18px;line-height:1.4;margin:0 0 12px;}"
                + ".hint{font-size:14px;line-height:1.6;color:#5b6165;margin:0 0 18px;}"
                + "dl{margin:0 0 22px;font-size:13px;line-height:1.7;}"
                + "dt{color:#7b8286;margin-top:10px;}dd{margin:2px 0 0;word-break:break-all;}"
                + ".mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;"
                + "background:#ececea;border-radius:6px;padding:8px 10px;}"
                + "button{display:block;width:100%;min-height:46px;margin-top:12px;border-radius:8px;"
                + "border:1px solid #2f6f5e;background:#2f6f5e;color:#fff;font-size:15px;font-weight:600;}"
                + "button.secondary{background:transparent;color:#2f6f5e;}"
                + "</style></head><body><main><h1>" + escapeHtml(title) + "</h1>"
                + bodyHtml
                + "</main><script>" + script + "</script></body></html>";
    }

    private static String escapeHtml(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#39;");
    }

    /** 用于把字符串安全地嵌进单引号包裹的 JS 字面量。 */
    private static String escapeJsString(String value) {
        if (value == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder(value.length() + 8);
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (current == '\\' || current == '\'' || current == '"') {
                builder.append('\\').append(current);
            } else if (current == '\n') {
                builder.append("\\n");
            } else if (current == '\r') {
                builder.append("\\r");
            } else if (current == '<') {
                // 避免 </script> 提前闭合脚本块。
                builder.append("\\u003c");
            } else {
                builder.append(current);
            }
        }
        return builder.toString();
    }
}
