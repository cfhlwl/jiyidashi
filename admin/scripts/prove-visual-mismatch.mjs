import { spawnSync } from 'node:child_process'

const result = spawnSync(
  process.platform === 'win32' ? 'npx.cmd' : 'npx',
  [
    'playwright',
    'test',
    'tests/visual/mismatch.spec.ts',
    '--project=desktop-1440',
  ],
  {
    cwd: new URL('..', import.meta.url),
    env: { ...process.env, ADMIN_VISUAL_MISMATCH_PROOF: '1' },
    stdio: 'inherit',
    shell: false,
  },
)

if (result.status === 0) {
  console.error('Intentional visual mismatch unexpectedly passed')
  process.exit(1)
}

console.log('Admin visual mismatch proof PASS: intentional mismatch was detected')
