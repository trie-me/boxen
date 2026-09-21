const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

// SHA-256's first byte for the fixed ASCII prefix + seven validated payload
// characters. This always fits in one padded block. It is a label checksum,
// not authentication; using it locally preserves v1 labels on plain LAN HTTP,
// where browsers do not expose SubtleCrypto.
function localChecksumByte(input: Uint8Array): number {
  const rounds = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const words = new Uint32Array(64);
  for (let i = 0; i < input.length; i++)
    words[i >>> 2] |= input[i] << (24 - (i % 4) * 8);
  words[input.length >>> 2] |= 0x80 << (24 - (input.length % 4) * 8);
  words[15] = input.length * 8;
  const rotate = (value: number, bits: number) =>
    (value >>> bits) | (value << (32 - bits));
  for (let i = 16; i < 64; i++) {
    const x = words[i - 15],
      y = words[i - 2];
    const s0 = rotate(x, 7) ^ rotate(x, 18) ^ (x >>> 3);
    const s1 = rotate(y, 17) ^ rotate(y, 19) ^ (y >>> 10);
    words[i] = words[i - 16] + s0 + words[i - 7] + s1;
  }
  let a = 0x6a09e667,
    b = 0xbb67ae85,
    c = 0x3c6ef372,
    d = 0xa54ff53a,
    e = 0x510e527f,
    f = 0x9b05688c,
    g = 0x1f83d9ab,
    h = 0x5be0cd19;
  for (let i = 0; i < 64; i++) {
    const s1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
    const choose = (e & f) ^ (~e & g);
    const t1 = (h + s1 + choose + rounds[i] + words[i]) | 0;
    const s0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
    const majority = (a & b) ^ (a & c) ^ (b & c);
    const t2 = (s0 + majority) | 0;
    h = g;
    g = f;
    f = e;
    e = (d + t1) | 0;
    d = c;
    c = b;
    b = a;
    a = (t1 + t2) | 0;
  }
  return ((0x6a09e667 + a) >>> 24) & 0xff;
}

export async function normalizeCode(raw: string): Promise<string> {
  if (raw.length > 64 || !/^[\x00-\x7f]+$/.test(raw))
    throw new Error("Enter the code printed on your Boxen label.");
  const compact = raw
    .toUpperCase()
    .replace(/[- ]/g, "")
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1");
  if (!/^BX[0-9A-HJKMNP-TV-Z]{8}$/.test(compact))
    throw new Error(
      "The code format is invalid. Use a code like BX-7K3M-R9QA.",
    );
  const input = new TextEncoder().encode(
    "BOXEN-BOX-CODE-V1:" + compact.slice(2, 9),
  );
  const firstByte = globalThis.crypto?.subtle
    ? new Uint8Array(await crypto.subtle.digest("SHA-256", input))[0]
    : localChecksumByte(input);
  if (compact[9] !== alphabet[firstByte & 31])
    throw new Error(
      "The check character does not match. Check the printed code.",
    );
  return "BX-" + compact.slice(2, 6) + "-" + compact.slice(6);
}
export async function validatePayload(raw: string): Promise<string> {
  raw = raw.trim();
  if (raw.startsWith("boxen:")) {
    const parts = raw.split(":");
    if (parts[1] !== "v1")
      throw new Error("This label uses an unsupported Boxen version.");
    if (parts.length !== 3)
      throw new Error("This is not a complete Boxen label.");
    return normalizeCode(parts[2]);
  }
  if (raw.includes("://")) {
    const url = new URL(raw);
    if (
      url.origin !== location.origin ||
      url.search ||
      url.hash ||
      url.username ||
      url.password ||
      !/^\/boxes\/BX-[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(url.pathname)
    )
      throw new Error("This URL is not a label from this Boxen host.");
    return normalizeCode(url.pathname.slice(7));
  }
  return normalizeCode(raw);
}
