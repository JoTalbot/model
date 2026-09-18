const OCTOPUS_KEY = new Uint8Array(32);
crypto.getRandomValues(OCTOPUS_KEY);

async function encryptMemory(data, key) {
  const enc = new TextEncoder();
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const keyMaterial = await crypto.subtle.importKey(
    'raw', key, { name: 'AES-GCM' }, false, ['encrypt']
  );
  const ct = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: iv }, keyMaterial, enc.encode(data)
  );
  return { iv: Array.from(iv), ct: Array.from(new Uint8Array(ct)) };
}

async function decryptMemory(iv, ct, key) {
  const keyMaterial = await crypto.subtle.importKey(
    'raw', key, { name: 'AES-GCM' }, false, ['decrypt']
  );
  const decrypted = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: new Uint8Array(iv) }, keyMaterial, new Uint8Array(ct)
  );
  return new TextDecoder().decode(decrypted);
}

console.log('WebCrypto AES-256-GCM initialized');
