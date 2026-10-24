document.addEventListener('allauth.error', event => {
  const feedback = document.getElementById('passkey-feedback');
  if (!feedback) return;
  event.preventDefault();
  const name = event.detail?.exception?.name;
  let message = 'We could not complete the passkey request. Try again or use your password and authenticator code.';
  if (name === 'NotAllowedError' || name === 'AbortError') {
    message = 'The passkey request was cancelled or timed out. Try again or use another sign-in method.';
  } else if (name === 'InvalidStateError') {
    message = 'This security key may already be registered. Check your existing keys or use another device.';
  } else if (name === 'SecurityError' || !window.isSecureContext) {
    message = 'Passkeys need a secure connection to the correct site. Open the HTTPS website, or use localhost during local setup.';
  } else if (!window.PublicKeyCredential) {
    message = 'This browser does not support passkeys. Use another browser or sign in with your password and authenticator code.';
  }
  feedback.textContent = message;
  feedback.hidden = false;
  feedback.scrollIntoView({ block: 'nearest' });
});
