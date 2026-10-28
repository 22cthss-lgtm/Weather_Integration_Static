// @vitest-environment node
import { expect, test } from 'vitest';
import { normalizeBase } from '../scripts/pages-build.mjs';
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
