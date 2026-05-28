const isLocal =
  window.location.hostname === "127.0.0.1" ||
  window.location.hostname === "localhost";
window.API_BASE_URL = isLocal
  ? ""
  : "https://74hnwcflk1.execute-api.ap-southeast-1.amazonaws.com";

window.COGNITO_USER_POOL_ID = "ap-southeast-1_fFzMyETft";
window.COGNITO_CLIENT_ID = "2ges2hhlmjlrhco058hpo2h7ov";
