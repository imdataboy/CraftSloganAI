// Shared authenticated API transport. Keep provider secrets on the server.
window.API_BASE = 'http://127.0.0.1:5000';
window.apiFetch = async function (path, options = {}) {
  const url = new URL(path, window.API_BASE);
  if (url.origin !== new URL(window.API_BASE).origin) throw new Error('Untrusted API origin.');
  const token = localStorage.getItem('accessToken');
  if (!token) throw new Error('Please sign in first.');
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(url, {...options, headers, credentials: 'include'});
  if (response.status === 401) {
    localStorage.removeItem('accessToken');
    throw new Error('Your session expired. Please sign in again.');
  }
  return response;
};
window.signOut = function () {
  localStorage.removeItem('accessToken');
  // Do not leave private chats available to the next signed-in user.
  localStorage.removeItem('savedchats');
  Object.keys(localStorage).filter(key => key.startsWith('savedchats-v2:')).forEach(key => localStorage.removeItem(key));
  window.location.href = 'signin.html';
};
window.loadPrivateImage = async function (element, path) {
  if (!path) return;
  try {
    const response = await apiFetch(path);
    if (!response.ok) throw new Error('Image unavailable.');
    const url = URL.createObjectURL(await response.blob());
    element.onload = () => URL.revokeObjectURL(url);
    element.src = url;
  } catch (_) { element.alt = 'Image unavailable'; }
};
