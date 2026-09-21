import {
  BarcodeFormat,
  BinaryBitmap,
  DecodeHintType,
  HybridBinarizer,
  MultiFormatReader,
  RGBLuminanceSource,
} from "@zxing/library";
const reader = new MultiFormatReader();
const hints = new Map();
hints.set(DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.QR_CODE]);
hints.set(DecodeHintType.TRY_HARDER, true);
reader.setHints(hints);
// Perfect, tightly cropped QR uploads can confuse the general finder-pattern
// detector for certain masks. Try the library's pure-symbol path only after the
// normal photographic decoder fails, and only for uploads (not camera frames).
const pureReader = new MultiFormatReader();
pureReader.setHints(new Map([...hints, [DecodeHintType.PURE_BARCODE, true]]));
self.postMessage({ type: "ready" });
self.onmessage = (
  event: MessageEvent<{
    data: Uint8ClampedArray;
    width: number;
    height: number;
    id: number;
    allowPure?: boolean;
  }>,
) => {
  const { data, width, height, id } = event.data;
  const gray = new Uint8ClampedArray(width * height);
  for (let i = 0; i < gray.length; i++)
    gray[i] = (data[i * 4] + data[i * 4 + 1] * 2 + data[i * 4 + 2]) / 4;
  const bitmap = new BinaryBitmap(
    new HybridBinarizer(new RGBLuminanceSource(gray, width, height)),
  );
  try {
    let result;
    try {
      result = reader.decodeWithState(bitmap);
    } catch (error) {
      if (!event.data.allowPure) throw error;
      result = pureReader.decodeWithState(bitmap);
    }
    self.postMessage({ type: "result", id, text: result.getText() });
  } catch {
    self.postMessage({ type: "result", id, text: null });
  } finally {
    reader.reset();
    pureReader.reset();
  }
};
