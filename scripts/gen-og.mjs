// Regenerate the v3 social/OG card (1200x630) -> web/app/static/og-default.png.
// Renders with the brand fonts (decompress the subset woff2 to TTF first — resvg needs
// TTF/OTF). Run:
//   python -c "from fontTools.ttLib import TTFont; ..."   # produce pj800.ttf, jb700.ttf
//   node scripts/gen-og.mjs <dir-with-ttfs>
import { Resvg } from '@resvg/resvg-js';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const fontDir = process.argv[2];
if (!fontDir) { console.error('usage: node gen-og.mjs <dir-with-ttfs>'); process.exit(1); }
const STATIC = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'app', 'static');

const MARK = `
  <path d="M4 22C4 12.1 12.1 4 22 4h43v43c0 9.9-8.1 18-18 18H22C12.1 65 4 56.9 4 47V22Z" fill="#17334B"/>
  <path d="M35 53c0-9.9 8.1-18 18-18h43v43c0 9.9-8.1 18-18 18H53c-9.9 0-18-8.1-18-18V53Z" fill="#8FADE4"/>
  <path d="M35 53C35 43.1 43.1 35 53 35h12v12c0 9.9-8.1 18-18 18H35Z" fill="#F0BA98"/>`;

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#FBF8F2"/>
  <!-- brand echo: the diptych squares, quietly, on the right -->
  <rect x="980" y="150" width="150" height="150" rx="20" fill="#E2EBF8"/>
  <rect x="1030" y="330" width="150" height="150" rx="20" fill="#FCEDE2"/>
  <!-- mark + wordmark, top-left -->
  <g transform="translate(80,72) scale(0.62)">${MARK}</g>
  <text x="156" y="130" font-family="Plus Jakarta Sans" font-weight="800" font-size="44" fill="#17334B" letter-spacing="-1">JBHNTR</text>
  <!-- headline -->
  <text x="80" y="330" font-family="Plus Jakarta Sans" font-weight="800" font-size="70" fill="#17334B" letter-spacing="-2">Don't let job hunting</text>
  <text x="80" y="410" font-family="Plus Jakarta Sans" font-weight="800" font-size="70" fill="#35599A" letter-spacing="-2">become your next job.</text>
  <!-- eyebrow -->
  <text x="82" y="540" font-family="JetBrains Mono" font-weight="700" font-size="24" fill="#5B87D0" letter-spacing="5">AI JOB-SEARCH AGENT</text>
</svg>`;

const png = new Resvg(svg, {
  fitTo: { mode: 'width', value: 1200 },
  font: {
    fontFiles: [join(fontDir, 'pj800.ttf'), join(fontDir, 'pj700.ttf'),
                join(fontDir, 'dm400.ttf'), join(fontDir, 'jb700.ttf')],
    loadSystemFonts: false,
    defaultFontFamily: 'Plus Jakarta Sans',
  },
}).render().asPng();
writeFileSync(join(STATIC, 'og-default.png'), png);
console.log(`wrote og-default.png (${png.length} bytes)`);
