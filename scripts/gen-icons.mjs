// Rasterise the JBHNTR paired mark to PNG app-icons.
//
// Home-screen / apple-touch icons are rendered FULL-BLEED on the mark's warm-white
// ground (the OS applies its own rounding/mask), with the mark at ~64% so it clears
// Android's maskable safe zone. Run after any change to the mark geometry:
//   node scripts/gen-icons.mjs
// Requires @resvg/resvg-js (prebuilt binary, no system cairo). Bump asset_v ships them.
import { Resvg } from '@resvg/resvg-js';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const STATIC = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'app', 'static');

// Mark paths — kept identical to logo.svg (viewBox 0 0 100 100).
const MARK = `
  <path d="M4 22C4 12.1 12.1 4 22 4h43v43c0 9.9-8.1 18-18 18H22C12.1 65 4 56.9 4 47V22Z" fill="#17334B"/>
  <path d="M35 53c0-9.9 8.1-18 18-18h43v43c0 9.9-8.1 18-18 18H53c-9.9 0-18-8.1-18-18V53Z" fill="#8FADE4"/>
  <path d="M35 53C35 43.1 43.1 35 53 35h12v12c0 9.9-8.1 18-18 18H35Z" fill="#F0BA98"/>`;

function fullBleedSvg(n) {
  const s = (n * 0.64 / 100).toFixed(6);
  const t = (n * 0.18).toFixed(4);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${n}" height="${n}" viewBox="0 0 ${n} ${n}">`
    + `<rect width="${n}" height="${n}" fill="#FBF8F2"/>`
    + `<g transform="translate(${t},${t}) scale(${s})">${MARK}</g></svg>`;
}

for (const [name, n] of [['icon-192.png', 192], ['icon-512.png', 512]]) {
  const png = new Resvg(fullBleedSvg(n), { fitTo: { mode: 'width', value: n } }).render().asPng();
  writeFileSync(join(STATIC, name), png);
  console.log(`wrote ${name} (${png.length} bytes)`);
}
