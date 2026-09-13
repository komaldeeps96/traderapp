/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
  /** Set by the browser-test build; the read-only test hooks ship nowhere else. */
  readonly VITE_TEST_HOOKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
