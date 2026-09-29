import { randomBytes } from 'node:crypto';
import { createServer } from 'vite';

if (
  process.env.NODE_ENV === 'production' ||
  (process.env.BOS_ENVIRONMENT && process.env.BOS_ENVIRONMENT !== 'development')
) {
  throw new Error('npm run demo is available only in a development environment');
}

const password = randomBytes(12).toString('base64url');
process.env.BOS_ENVIRONMENT = 'development';
process.env.BOS_WEB_DEMO_LOGIN = '1';
process.env.VITE_BOS_DEMO_LOGIN = '1';
process.env.BOS_WEB_DEMO_PASSWORD = password;

const server = await createServer({
  server: { host: '127.0.0.1', port: 3000, strictPort: true },
});
await server.listen();
server.printUrls();
console.log('\nLocal demo login (development server only):');
console.log('  Admin:  admin@demo.businessos.test');
console.log('  Viewer: viewer@demo.businessos.test');
console.log(`  Password for both: ${password}`);
console.log('  Session state is in this local server process and disappears when it stops.\n');
