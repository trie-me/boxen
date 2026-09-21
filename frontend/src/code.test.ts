import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { normalizeCode, validatePayload } from "./code";

const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const origin = "http://boxen.test:8174";
function referenceCode(payload: string): string {
  const hash = createHash("sha256")
    .update("BOXEN-BOX-CODE-V1:" + payload)
    .digest();
  return `BX-${payload.slice(0, 4)}-${payload.slice(4)}${alphabet[hash[0] & 31]}`;
}

afterEach(() => vi.unstubAllGlobals());

describe.each(["secure context", "plain HTTP"])(
  "printed codes: %s",
  (context) => {
    beforeEach(() => {
      vi.stubGlobal("crypto", context === "secure context" ? webcrypto : {});
      vi.stubGlobal("location", new URL(origin));
    });
    it("matches the cross-language canonical vector", async () =>
      expect(await normalizeCode("bx 7k3m r9qa")).toBe("BX-7K3M-R9QA"));
    it("rejects a checksum mismatch", async () =>
      expect(normalizeCode("BX-7K3M-R9QB")).rejects.toThrow("check character"));
    it("rejects non-ASCII lookalikes", async () =>
      expect(normalizeCode("ΒX-7K3M-R9QA")).rejects.toThrow());

    it("matches independent SHA-256 for 256 distinct label payloads", async () => {
      for (let i = 0; i < 256; i++) {
        const value = BigInt(i) * 2654435761n;
        const payload = Array.from(
          { length: 7 },
          (_, index) =>
            alphabet[Number((value >> BigInt((6 - index) * 5)) & 31n)],
        ).join("");
        const code = referenceCode(payload);
        expect(await normalizeCode(code)).toBe(code);
      }
    });

    it("rejects all incorrect check characters", async () => {
      for (const check of alphabet.replace("A", ""))
        await expect(normalizeCode("BX-7K3M-R9Q" + check)).rejects.toThrow(
          "check character",
        );
    });

    it("keeps O/I/L aliases and separator normalization", async () => {
      const code = referenceCode("0011001");
      expect(
        await normalizeCode(
          code.replaceAll("0", "o").replaceAll("1", "l").replaceAll("-", " "),
        ),
      ).toBe(code);
      expect(await normalizeCode(code.replaceAll("1", "i"))).toBe(code);
    });

    it("resolves v1 QR payloads and exact same-host URLs", async () => {
      expect(await validatePayload(" boxen:v1:BX-7K3M-R9QA ")).toBe(
        "BX-7K3M-R9QA",
      );
      expect(await validatePayload(origin + "/boxes/BX-7K3M-R9QA")).toBe(
        "BX-7K3M-R9QA",
      );
    });

    it("keeps checksum validation for QR payloads and URLs", async () => {
      for (const input of [
        "boxen:v1:BX-7K3M-R9QB",
        origin + "/boxes/BX-7K3M-R9QB",
      ])
        await expect(validatePayload(input)).rejects.toThrow("check character");
    });

    it("rejects unsupported and malformed QR protocols", async () => {
      await expect(validatePayload("boxen:v2:BX-7K3M-R9QA")).rejects.toThrow(
        "unsupported",
      );
      await expect(
        validatePayload("boxen:v1:BX-7K3M-R9QA:extra"),
      ).rejects.toThrow("complete");
    });

    it("rejects foreign hosts, ports, schemes, credentials and URL additions", async () => {
      for (const input of [
        "http://other.test:8174/boxes/BX-7K3M-R9QA",
        "http://boxen.test:8175/boxes/BX-7K3M-R9QA",
        "https://boxen.test:8174/boxes/BX-7K3M-R9QA",
        "http://user@boxen.test:8174/boxes/BX-7K3M-R9QA",
        "http://:password@boxen.test:8174/boxes/BX-7K3M-R9QA",
        origin + "/boxes/BX-7K3M-R9QA?track=1",
        origin + "/boxes/BX-7K3M-R9QA#fragment",
        origin + "/boxes/BX-7K3M-R9QA/extra",
      ])
        await expect(validatePayload(input)).rejects.toThrow(
          "not a label from this Boxen host",
        );
    });
  },
);
