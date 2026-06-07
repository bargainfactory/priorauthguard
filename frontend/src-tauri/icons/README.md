# App icons

Tauri's bundler expects these files in this folder before `tauri build`:

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.icns` (macOS)
- `icon.ico` (Windows)

A one-shot pipeline is to generate them from a single 1024×1024 source PNG:

```bash
pnpm tauri icon ./icon-source.png
```

Until a final brand mark lands, this directory is intentionally empty —
`tauri build` will fail until icons exist, but `tauri dev` works.
