import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { target: ["chrome80", "safari14"], cssTarget: "safari14" },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
