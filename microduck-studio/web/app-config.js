/* The frontend may be hosted anywhere (e.g. Cloudflare Pages); the API, database and hardware
   always stay on the operator's machine. Same-origin when this page is served by the local
   service; loopback otherwise. Override per browser via localStorage['microduckStudioApiBase']. */
window.StudioAPI = (() => {
  const KEY = 'microduckStudioApiBase';
  const DEFAULT_REMOTE_BASE = 'http://127.0.0.1:8765';
  const isLocalHost = () => ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(location.hostname);
  const storedBase = () => {
    try { return localStorage.getItem(KEY); } catch { return null; }
  };
  const base = () => {
    const custom = (storedBase() || '').trim();
    if (custom) return custom.replace(/\/+$/, '');
    return isLocalHost() ? '' : DEFAULT_REMOTE_BASE;
  };
  const url = path => base() + path;
  const call = (path, init) => window.fetch(url(path), init);
  async function version() {
    const response = await call('/api/version');
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    return response.json();
  }
  return {KEY, base, url, fetch: call, version, isLocalHost, DEFAULT_REMOTE_BASE};
})();
