/* Hearthbeat phone E2E for live transcription (contract live_transcribe.md v2 + v2.1). WebCrypto only.
 * - per job: ephemeral P-256 keypair (private key never leaves this tab) -> client_pub
 * - per segment: random AES-256 key K; ct = AES-GCM(K, wav); for each recipient node: k = AES-GCM(HKDF(ECDH(eph, node_pub)), K)
 * - transcript: each segment's enc {eph, iv, ct} decrypted here with the job key; nothing readable reaches the coordinator
 * - v2.1: recompute the hash links, verify node Ed25519 signatures when the browser supports Ed25519
 * KDF: HKDF-SHA256, salt empty, info "dh-e2e-v1", 32 bytes. Keys as SPKI DER base64. IV 12 bytes. */
(function () {
  "use strict";
  const S = crypto.subtle, te = new TextEncoder(), td = new TextDecoder();
  const b64 = (buf) => { const a = new Uint8Array(buf); let s = ""; for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const hex = (buf) => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, "0")).join("");
  const EC = { name: "ECDH", namedCurve: "P-256" };
  const INFO = te.encode("dh-e2e-v1");

  async function genPair() { return S.generateKey(EC, false, ["deriveBits"]); }
  async function pubB64(k) { return b64(await S.exportKey("spki", k.publicKey)); }
  async function importPub(b) { return S.importKey("spki", unb64(b), EC, false, []); }
  async function kdf(priv, pub) {
    const shared = await S.deriveBits({ name: "ECDH", public: pub }, priv, 256);
    const hk = await S.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
    return S.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: INFO }, hk, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  const iv12 = () => crypto.getRandomValues(new Uint8Array(12));
  const sha = async (bytes) => S.digest("SHA-256", bytes);

  /* encrypt one WAV segment for all recipients -> JSON blob (string) */
  async function sealSegment(wavBlob, recipients) {
    const wav = new Uint8Array(await wavBlob.arrayBuffer());
    const Kraw = crypto.getRandomValues(new Uint8Array(32));
    const K = await S.importKey("raw", Kraw, "AES-GCM", false, ["encrypt"]);
    const iv = iv12(), ct = await S.encrypt({ name: "AES-GCM", iv }, K, wav);
    const wraps = {};
    for (const r of recipients) {
      const eph = await genPair(), key = await kdf(eph.privateKey, await importPub(r.e2e_pub)), wiv = iv12();
      wraps[r.node_id] = { eph: await pubB64(eph), iv: b64(wiv), k: b64(await S.encrypt({ name: "AES-GCM", iv: wiv }, key, Kraw)) };
    }
    return JSON.stringify({ v: 1, iv: b64(iv), ct: b64(ct), wraps });
  }

  /* decrypt a node's transcript ciphertext {eph, iv, ct} with the job keypair */
  async function openText(jobPair, enc) {
    const key = await kdf(jobPair.privateKey, await importPub(enc.eph));
    return td.decode(await S.decrypt({ name: "AES-GCM", iv: unb64(enc.iv) }, key, unb64(enc.ct)));
  }

  /* v2.1: verify the hash chain + signatures that the coordinator returns per segment */
  let ed = null;
  async function edOk() { if (ed !== null) return ed; try { await S.importKey("raw", new Uint8Array(32), { name: "Ed25519" }, false, ["verify"]); ed = true; } catch (e) { ed = false; } return ed; }
  async function verifySegments(jobId, segs) {
    let prev = await sha(te.encode(jobId)), chainOk = true, sigs = 0, sigOk = 0;
    const out = [];
    for (const s of segs) {
      let ok = null;
      if (s.blob_sha256 && s.enc_sha256 && s.link) {
        const buf = new Uint8Array([...new Uint8Array(prev), ...unb64h(s.blob_sha256), ...unb64h(s.enc_sha256), ...te.encode(s.node || "")]);
        const link = hex(await sha(buf));
        ok = link === s.link; if (!ok) chainOk = false; prev = unb64h(link).buffer;
      }
      let sig = null;
      if (s.sig && s.sig_pub && (await edOk())) {
        sigs++;
        try {
          const k = await S.importKey("raw", unb64(s.sig_pub), { name: "Ed25519" }, false, ["verify"]);
          const m = te.encode(`dh-seg-v1|${jobId}|${s.seq}|${s.blob_sha256}|${s.enc_sha256}`);
          sig = await S.verify({ name: "Ed25519" }, k, unb64(s.sig), m); if (sig) sigOk++;
        } catch (e) { sig = false; }
      }
      out.push({ seq: s.seq, link: ok, sig });
    }
    return { chainOk, sigs, sigOk, ed: await edOk(), per: out };
  }
  function unb64h(h) { const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16); return a; }

  window.DHE2E = { genPair, pubB64, sealSegment, openText, verifySegments, supported: !!(window.crypto && crypto.subtle) };
})();
