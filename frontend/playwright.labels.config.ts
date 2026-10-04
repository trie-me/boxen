import { defineConfig } from "@playwright/test";
import lan from "./playwright.lan.config";
export default defineConfig({
  ...lan,
  testMatch: ["label-printing.spec.ts"],
  outputDir: "test-results-labels",
});
