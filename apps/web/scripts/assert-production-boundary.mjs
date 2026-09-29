import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

const assets = join(import.meta.dirname, '..', 'dist', 'assets');
const names = await readdir(assets);
const markers = [
  '/dev/demo-login',
  'admin@demo.businessos.test',
  'viewer@demo.businessos.test',
  'bos_demo_session',
];

for (const name of names.filter((item) => item.endsWith('.js'))) {
  const content = await readFile(join(assets, name), 'utf8');
  if (name.includes('DemoLoginPage') || markers.some((marker) => content.includes(marker))) {
    throw new Error(`Development demo authentication leaked into production asset ${name}`);
  }
}

console.log('Production bundle excludes demo authentication and demo credentials.');
