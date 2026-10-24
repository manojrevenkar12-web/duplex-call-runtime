import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// framer-motion asks for these in jsdom
window.matchMedia ??= ((q: string) => ({
  matches: false, media: q, onchange: null, addListener() {}, removeListener() {},
  addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;
Element.prototype.scrollIntoView ??= function () {};

// jsdom has no canvas; give the spectrogram a context that records nothing
HTMLCanvasElement.prototype.getContext = function () {
  return {
    createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
    putImageData() {},
  };
} as unknown as typeof HTMLCanvasElement.prototype.getContext;
