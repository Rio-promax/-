package com.catsk.multisourcekb;

import android.content.Context;
import android.content.SharedPreferences;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

/**
 * 访问凭据存储。
 *
 * <p><b>安全取舍（有意为之，请勿误删注释）</b>：默认使用
 * {@link EncryptedSharedPreferences}，密钥由 Android Keystore 托管（AES256-GCM），
 * 密码以密文落盘。若设备 Keystore 异常导致初始化失败，则退到普通
 * {@link SharedPreferences}，此时密码<b>以明文</b>存放在 App 私有目录
 * {@code /data/data/com.catsk.multisourcekb/shared_prefs/} 下——只有 root
 * 或同一 uid 的进程能读到。
 *
 * <p>选这个取舍而不是「失败就崩」的原因是：Keystore 在部分定制 ROM / 恢复出厂
 * 后的旧数据上会初始化失败，直接崩会让整个壳不可用。若要更严格的策略，删掉
 * {@code catch} 分支让它失败即可。
 *
 * <p>已知副作用：一旦某次运行落到 fallback 分支，之后即使 Keystore 恢复，
 * 也会读不到先前明文存的密码（两个文件名不同），需要重新输入一次。这是
 * 为了避免「把密文文件当明文读」而故意分开文件名。
 */
final class CredentialStore {

    private static final String PREFS_ENCRYPTED = "kb_credentials";
    private static final String PREFS_FALLBACK = "kb_credentials_fallback";
    private static final String KEY_USERNAME = "username";
    private static final String KEY_PASSWORD = "password";

    private CredentialStore() {
        // 纯静态工具类。
    }

    private static SharedPreferences prefs(Context context) {
        Context app = context.getApplicationContext();
        try {
            MasterKey masterKey = new MasterKey.Builder(app)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            return EncryptedSharedPreferences.create(
                    app,
                    PREFS_ENCRYPTED,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
        } catch (Exception error) {
            // 见类注释的取舍说明：宁可退到明文私有存储，也不让壳无法使用。
            return app.getSharedPreferences(PREFS_FALLBACK, Context.MODE_PRIVATE);
        }
    }

    /** 用户名，未设置时返回默认值 {@code kb}。 */
    static String getUsername(Context context) {
        String stored = prefs(context).getString(KEY_USERNAME, null);
        if (stored == null || stored.trim().isEmpty()) {
            return ShellConfig.DEFAULT_USERNAME;
        }
        return stored.trim();
    }

    /** 密码；未设置时返回 {@code null}（调用方必须判空）。 */
    static String getPassword(Context context) {
        String stored = prefs(context).getString(KEY_PASSWORD, null);
        if (stored == null || stored.isEmpty()) {
            return null;
        }
        return stored;
    }

    /** 是否已经录入过密码。 */
    static boolean hasPassword(Context context) {
        return getPassword(context) != null;
    }

    static void save(Context context, String username, String password) {
        SharedPreferences.Editor editor = prefs(context).edit();
        String normalizedUser = (username == null || username.trim().isEmpty())
                ? ShellConfig.DEFAULT_USERNAME
                : username.trim();
        editor.putString(KEY_USERNAME, normalizedUser);
        editor.putString(KEY_PASSWORD, password == null ? "" : password);
        editor.apply();
    }

    static void clear(Context context) {
        prefs(context).edit().clear().apply();
    }
}
