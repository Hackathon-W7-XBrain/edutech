import { api, showToast } from "./api.js";
import { clearUserId, getUserId, setUserId, clearToken, setToken } from "./session.js";

export function bindAuth({ onAuthChange }) {
  const overlay = document.getElementById("auth-overlay");
  const userField = document.getElementById("auth-user");
  const passField = document.getElementById("auth-pass");
  const errorField = document.getElementById("auth-error");
  const loginBtn = document.getElementById("auth-login");
  const registerBtn = document.getElementById("auth-register");
  const logoutBtn = document.getElementById("logout-btn");
  const userLabel = document.getElementById("user-label");

  let userPool = null;
  if (typeof AmazonCognitoIdentity !== 'undefined' && window.COGNITO_USER_POOL_ID) {
    const poolData = {
      UserPoolId: window.COGNITO_USER_POOL_ID,
      ClientId: window.COGNITO_CLIENT_ID
    };
    userPool = new AmazonCognitoIdentity.CognitoUserPool(poolData);
  }

  function login() {
    let username = userField.value.trim();
    const password = passField.value;
    if (!username || !password) {
      errorField.textContent = "Fill in both fields";
      return;
    }
    
    // Keep original name for display
    const displayName = username.includes("@") ? username.split("@")[0] : username;
    // Auto-convert to email format for Cognito
    if (!username.includes("@")) {
      username = username + "@studybot.local";
    }

    if (!userPool) {
      errorField.textContent = "Cognito SDK is not initialized.";
      return;
    }

    const authenticationDetails = new AmazonCognitoIdentity.AuthenticationDetails({
      Username: username,
      Password: password,
    });

    const userData = {
      Username: username,
      Pool: userPool,
    };
    const cognitoUser = new AmazonCognitoIdentity.CognitoUser(userData);

    cognitoUser.authenticateUser(authenticationDetails, {
      onSuccess: function (result) {
        const idToken = result.getIdToken().getJwtToken();
        setToken(idToken);
        setUserId(displayName);
        
        overlay.classList.remove("open");
        if (userLabel) userLabel.textContent = displayName;
        errorField.textContent = "";
        showToast(`Signed in as ${displayName}`, "success");
        onAuthChange?.(displayName);
      },
      onFailure: function (err) {
        errorField.textContent = err.message || JSON.stringify(err);
      },
    });
  }

  function register() {
    let username = userField.value.trim();
    const password = passField.value;
    if (!username || !password) {
      errorField.textContent = "Fill in both fields";
      return;
    }

    if (!username.includes("@")) {
      username = username + "@studybot.local";
    }

    if (!userPool) {
      errorField.textContent = "Cognito SDK is not initialized.";
      return;
    }

    userPool.signUp(username, password, [], null, function (err, result) {
      if (err) {
        errorField.textContent = err.message || JSON.stringify(err);
        return;
      }
      showToast(`Created ${username}, logging in...`, "success");
      login();
    });
  }

  loginBtn?.addEventListener("click", login);
  registerBtn?.addEventListener("click", register);
  logoutBtn?.addEventListener("click", () => {
    if (userPool) {
      const currentUser = userPool.getCurrentUser();
      if (currentUser) {
          currentUser.signOut();
      }
    }
    clearUserId();
    clearToken();
    overlay.classList.add("open");
    if (userLabel) userLabel.textContent = "";
    onAuthChange?.("");
  });
  passField?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      login();
    }
  });

  const currentUser = getUserId();
  if (currentUser) {
    overlay.classList.remove("open");
    if (userLabel) userLabel.textContent = currentUser;
    onAuthChange?.(currentUser);
  } else {
    overlay.classList.add("open");
  }

  window.addEventListener("studybot:unauthorized", () => {
    if (userPool) {
      const cognitoUser = userPool.getCurrentUser();
      if (cognitoUser) cognitoUser.signOut();
    }
    clearUserId();
    clearToken();
    overlay.classList.add("open");
    if (userLabel) userLabel.textContent = "";
    if (errorField) errorField.textContent = "Session expired. Sign in again.";
    onAuthChange?.("");
  });
}
