/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Workspace name or slug to focus on at startup (overridden by ?workspace= URL param). */
  readonly VITE_DEFAULT_WORKSPACE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
