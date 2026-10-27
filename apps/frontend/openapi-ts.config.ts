import { defineConfig } from "@hey-api/openapi-ts";
export default defineConfig({
  input: ".openapi.json",
  output: { path: "src/shared/api/generated", postProcess: [] },
  plugins: ["@hey-api/typescript"],
});
