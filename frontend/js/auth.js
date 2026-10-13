async function authenticate(provider) {
  try {
    const response = await apiFetch(`/auth/${provider}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Connection failed.');
    window.location.href = result.auth_url;
  } catch (error) { alert(error.message); }
}
function authenticateGmail() { return authenticate('gmail'); }
function authenticateLinkedIn() { return authenticate('linkedin'); }
async function checkStatus() {
  const gmail = document.getElementById('gmailButton');
  const linkedin = document.getElementById('linkedinButton');
  if (!gmail && !linkedin) return;
  try {
    if (gmail) {
      const response = await apiFetch('/auth/gmail/status');
      const status = await response.json();
      if (!response.ok) throw new Error(status.error || 'Status unavailable.');
      gmail.textContent = status.connected ? 'Generate AI-Driven Post' : 'Connect to Gmail';
      gmail.disabled = false;
      gmail.onclick = status.connected ? showExtractInsights : authenticateGmail;
    }
    // Manual generation does not need LinkedIn credentials; publication does.
    if (linkedin) {
      linkedin.textContent = 'Describe Product';
      linkedin.disabled = false;
      linkedin.onclick = showGenerateEmail;
    }
  } catch (error) { alert(error.message); }
}
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('connectGmail')?.addEventListener('click', authenticateGmail);
  document.getElementById('connectLinkedIn')?.addEventListener('click', authenticateLinkedIn);
  checkStatus();
});
