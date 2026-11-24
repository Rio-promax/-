const logoutButton = document.querySelector("#account-logout");

if (logoutButton) {
  fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" })
    .then((response) => {
      if (response.ok) logoutButton.hidden = false;
    })
    .catch(() => {});

  logoutButton.addEventListener("click", async () => {
    logoutButton.disabled = true;
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } finally {
      window.location.replace("/login");
    }
  });
}
