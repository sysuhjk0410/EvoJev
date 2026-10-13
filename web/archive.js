'use strict';
(() => {
  const pending = new Map();
  const cache = new Map();
  const staticMode = document.documentElement.dataset.archive === 'static';
  const deliver = async (key, encoded) => {
    const request = pending.get(key);
    if (!request) return;
    try {
      if (typeof DecompressionStream !== 'function') throw new Error('A current browser is required to read the result archive.');
      const bytes = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      const value = JSON.parse(await new Response(stream).text());
      cache.set(key, value);
      if (cache.size > 5) cache.delete([...cache.keys()].find(name => name !== 'progress' && name !== key));
      request.resolve(value);
    } catch (error) {
      request.reject(error);
    } finally {
      clearTimeout(request.timeout);
      request.script.remove();
      pending.delete(key);
    }
  };
  function load(key) {
    if (cache.has(key)) return Promise.resolve(cache.get(key));
    if (pending.has(key)) return pending.get(key).promise;
    const script = document.createElement('script');
    const file = key === 'progress' ? 'progress.js' : 'cases/' + key + '.js';
    script.src = new URL('web/archive/' + file, document.baseURI).href;
    script.async = true;
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    const fail = () => {
      clearTimeout(pending.get(key)?.timeout);
      script.remove();
      pending.delete(key);
      reject(new Error('Result archive unavailable: ' + key));
    };
    const timeout = setTimeout(fail, 30000);
    pending.set(key, {promise, resolve, reject, script, timeout});
    script.onerror = fail;
    document.head.append(script);
    return promise;
  }
  async function api(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error('Result archive unavailable');
    return response.json();
  }
  window.EvoJevArchive = {
    deliver,
    progress: () => staticMode ? load('progress') : api('/api/progress'),
    case: id => {
      if (!/^case_\d{4}$/.test(id)) return Promise.reject(new Error('Invalid case'));
      return staticMode ? load(id) : api('/api/case?id=' + encodeURIComponent(id));
    }
  };
})();
