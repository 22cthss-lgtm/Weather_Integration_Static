// @vitest-environment node
import { expect, test } from 'vitest';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { appRoutes, normalizeBase, writeStaticEntries } from '../scripts/pages-build.mjs';
import { imageTypes } from './image-types';

test('Pages base accepts root and repository paths, rejects external/traversal paths', () => {
  expect(normalizeBase('')).toBe('/');
  expect(normalizeBase('/')).toBe('/');
  expect(normalizeBase('/weather-test')).toBe('/weather-test/');
  expect(normalizeBase('/weather-test/')).toBe('/weather-test/');
  for (const value of ['https://example.com/', '//example.com/', '/../', '/repo/../', 'repo', '/a?b']) {
    expect(() => normalizeBase(value)).toThrow();
  }
  expect(new Set(imageTypes).size).toBe(12);
});

test('static entries cover every image detail page and the tropical page', async () => {
  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'pages-build-'));
  try {
    const html = '<script src="/repo/assets/app.js"></script>';
    await fs.writeFile(path.join(outDir, 'index.html'), html);
    const routes = await writeStaticEntries(outDir);
    expect(appRoutes).toEqual(['tropical']);
    expect(imageTypes).not.toContain('tropical');
    expect(routes).toHaveLength(imageTypes.length + 1);
    for (const route of [...imageTypes.map(type => `images/${type}`), 'tropical']) {
      expect(await fs.readFile(path.join(outDir, route, 'index.html'), 'utf8')).toBe(html);
    }
  } finally {
    await fs.rm(outDir, { recursive: true, force: true });
  }
});

test('static entries fail when the built entry is missing', async () => {
  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), 'pages-build-'));
  try {
    await expect(writeStaticEntries(outDir)).rejects.toThrow();
  } finally {
    await fs.rm(outDir, { recursive: true, force: true });
  }
});
