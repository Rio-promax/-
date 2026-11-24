const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const loginSubmit = document.querySelector("#login-submit");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  loginSubmit.disabled = true;
  const form = new FormData(loginForm);
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    if (!response.ok) {
      loginError.textContent = response.status === 401 || response.status === 422
        ? "账号或密码不正确"
        : "登录失败";
      loginError.hidden = false;
      return;
    }
    window.location.replace("/");
  } catch {
    loginError.textContent = "无法连接服务";
    loginError.hidden = false;
  } finally {
    loginSubmit.disabled = false;
  }
});
