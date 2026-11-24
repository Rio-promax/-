package com.catsk.multisourcekb;

import android.content.Context;
import android.util.Base64;
import android.util.Log;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * 分享链接导入的 HTTP 调用。
 *
 * <p>契约来自服务端 {@code POST /api/v1/imports/link}（见 {@code app/api/schemas.py}
 * 的 {@code LinkImportRequest}）：请求体最小只需要 {@code {"url": "..."}}，
 * 成功返回 <b>201</b>。其余字段（model / summary_template / strength 等）全部有默认值，
 * 壳不传，由服务端配置决定——壳里不塞任何业务逻辑。
 *
 * <p>站点密码门在反向代理层，所以这里必须自带 {@code Authorization: Basic ...}，
 * 否则会拿到 401。
 */
final class HttpPoster {

    private static final String TAG = "HttpPoster";
    private static final int MAX_BODY_CHARS = 400;

    /** 调用结果，供界面直接展示。 */
    static final class Result {

        final boolean success;
        final String message;

        Result(boolean success, String message) {
            this.success = success;
            this.message = message;
        }
    }

    private HttpPoster() {
        // 纯静态工具类。
    }

    static Result postImportLink(Context context, String url) {
        String username = CredentialStore.getUsername(context);
        String password = CredentialStore.getPassword(context);
        if (password == null || password.isEmpty()) {
            return new Result(false, "尚未设置访问密码，请先打开「多源知识库」完成设置");
        }

        HttpURLConnection connection = null;
        try {
            JSONObject body = new JSONObject();
            body.put("url", url);
            byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);

            connection = (HttpURLConnection) new URL(ShellConfig.IMPORT_LINK_ENDPOINT).openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(ShellConfig.HTTP_CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(ShellConfig.HTTP_READ_TIMEOUT_MS);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Authorization", basicAuthHeader(username, password));

            OutputStream output = connection.getOutputStream();
            try {
                output.write(payload);
                output.flush();
            } finally {
                output.close();
            }

            int statusCode = connection.getResponseCode();
            String responseBody = readBody(
                    statusCode >= 400 ? connection.getErrorStream() : connection.getInputStream());

            if (statusCode >= 200 && statusCode < 300) {
                return new Result(true, "任务已进入处理队列，可在「任务」页查看进度");
            }
            if (statusCode == 401) {
                return new Result(false, "访问密码不正确（HTTP 401），请打开 App 重新输入密码");
            }
            if (statusCode == 422) {
                return new Result(false, "该链接无法导入：" + shorten(responseBody));
            }
            return new Result(false, "导入失败（HTTP " + statusCode + "）" + shorten(responseBody));
        } catch (IOException error) {
            Log.w(TAG, "postImportLink failed", error);
            return new Result(false, "连不上服务器：" + ShellConfig.SERVER_ORIGIN);
        } catch (JSONException error) {
            Log.w(TAG, "postImportLink body error", error);
            return new Result(false, "请求构造失败：" + error.getMessage());
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String basicAuthHeader(String username, String password) {
        String raw = username + ":" + (password == null ? "" : password);
        return "Basic " + Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
    }

    private static String readBody(InputStream stream) {
        if (stream == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        BufferedReader reader = null;
        try {
            reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
        } catch (IOException error) {
            Log.w(TAG, "readBody failed", error);
        } finally {
            if (reader != null) {
                try {
                    reader.close();
                } catch (IOException ignored) {
                    // 关闭失败不影响结果判定。
                }
            }
        }
        return builder.toString();
    }

    private static String shorten(String body) {
        if (body == null || body.isEmpty()) {
            return "";
        }
        String trimmed = body.trim();
        if (trimmed.length() <= MAX_BODY_CHARS) {
            return "：" + trimmed;
        }
        return "：" + trimmed.substring(0, MAX_BODY_CHARS) + "…";
    }
}
