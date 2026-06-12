(function () {
    const stage = document.querySelector("[data-auth-stage]");
    const passwordField = document.querySelector("[data-password-field]");
    const passwordInput = passwordField?.querySelector("input[name='password']");
    const passwordToggle = passwordField?.querySelector("[data-password-toggle]");

    if (passwordField && passwordInput && passwordToggle) {
        const syncPasswordToggle = () => {
            const hasValue = passwordInput.value.length > 0;
            passwordField.classList.toggle("has-value", hasValue);

            if (!hasValue) {
                passwordInput.type = "password";
                passwordToggle.setAttribute("aria-pressed", "false");
                passwordToggle.setAttribute("aria-label", "显示密码");
                stage?.classList.remove("is-looking-away");
            }
        };

        passwordToggle.addEventListener("click", () => {
            const shouldShow = passwordInput.type === "password";
            passwordInput.type = shouldShow ? "text" : "password";
            passwordToggle.setAttribute("aria-pressed", shouldShow ? "true" : "false");
            passwordToggle.setAttribute("aria-label", shouldShow ? "隐藏密码" : "显示密码");
            stage?.classList.toggle("is-looking-away", shouldShow);
            passwordInput.focus({ preventScroll: true });
        });

        passwordInput.addEventListener("input", syncPasswordToggle);
        syncPasswordToggle();
    }
})();
