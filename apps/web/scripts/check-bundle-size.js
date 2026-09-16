import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, '../dist/assets');

if (!fs.existsSync(distDir)) {
  console.error('Error: dist/assets does not exist. Run build first.');
  process.exit(1);
}

const files = fs.readdirSync(distDir);
let totalJsSize = 0;
let totalCssSize = 0;
const MAX_ENTRY_CHUNK_KB = 500;
const MAX_TOTAL_JS_KB = 1200;

console.log('--- Production Bundle Size Audit ---');
files.forEach((file) => {
  const filePath = path.join(distDir, file);
  const stats = fs.statSync(filePath);
  const sizeKb = (stats.size / 1024).toFixed(2);
  console.log('- ' + file + ': ' + sizeKb + ' KB');
  if (file.endsWith('.js')) {
    totalJsSize += stats.size;
    if (stats.size / 1024 > MAX_ENTRY_CHUNK_KB) {
      console.warn('Warning: Chunk ' + file + ' exceeds target ' + MAX_ENTRY_CHUNK_KB + ' KB');
    }
  } else if (file.endsWith('.css')) {
    totalCssSize += stats.size;
  }
});

const totalJsKb = (totalJsSize / 1024).toFixed(2);
const totalCssKb = (totalCssSize / 1024).toFixed(2);
console.log('Total JS: ' + totalJsKb + ' KB');
console.log('Total CSS: ' + totalCssKb + ' KB');

if (totalJsSize / 1024 > MAX_TOTAL_JS_KB) {
  console.error('FAILED: Total JS (' + totalJsKb + ' KB) exceeds budget (' + MAX_TOTAL_JS_KB + ' KB).');
  process.exit(1);
}

console.log('Bundle size within performance budget thresholds.');
