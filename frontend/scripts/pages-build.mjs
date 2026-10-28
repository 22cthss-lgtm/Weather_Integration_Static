import { build } from 'vite';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { imageTypes } from '../src/image-types.js';

export function normalizeBase(value = '/') {
  if (!value) return '/';
  if (!/^(?:\/[A-Za-z0-9_.~-]+)*\/?$/.test(value)
      || value.split('/').some(part => part === '.' || part === '..')) {
    throw new Error('Pages base must be a local absolute URL path');
  }
  return value.endsWith('/') ? value : `${value}/`;
}

export async function buildPages({ root = fileURLToPath(new URL('../', import.meta.url)),
  base = '/', outDir = path.join(root, 'dist') } = {}) {
  base = normalizeBase(base);
  await build({ root, configFile: path.join(root, 'vite.config.js'), base,
    build: { outDir, emptyOutDir: true } });
  const entry = await fs.readFile(path.join(outDir, 'index.html'));
  for (const type of imageTypes) {
    const directory = path.join(outDir, 'images', type);
    await fs.mkdir(directory, { recursive: true });
    await fs.writeFile(path.join(directory, 'index.html'), entry);
  }
  await fs.writeFile(path.join(outDir, '.nojekyll'), '');
  console.log(`Pages: base=${base}; ${imageTypes.length} real detail entry points`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildPages({ base: process.env.PAGES_BASE_PATH || '/' });
}
