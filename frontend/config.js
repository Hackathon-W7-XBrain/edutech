const isLocal =
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname === "localhost";
window.API_BASE_URL = isLocal
  ? ""
  : "https://540rls5sxg.execute-api.ap-southeast-1.amazonaws.com";

window.COGNITO_USER_POOL_ID = "ap-southeast-1_39LOCIDa9";
window.COGNITO_CLIENT_ID = "1g7erhnlrrlgh7074rff2jnith";
