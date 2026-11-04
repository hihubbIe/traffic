import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend is a standalone static app; it talks to the backend API over HTTP
// (see src/api.ts for how the API URL is chosen).
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
  preview: { host: true, port: 4173 },
});
