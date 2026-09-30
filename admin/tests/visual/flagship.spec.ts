import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const userId = '11111111-1111-4111-8111-111111111111'
const familyId = '33333333-3333-4333-8333-333333333333'

const screens = [
  ['login', '/login?review=login'],
  ['dashboard', '/'],
  ['users', '/users'],
  ['user-detail', '/users/' + userId],
  ['families', '/families'],
  ['family-detail', '/families/' + familyId],
  ['entitlements', '/entitlements'],
  ['data-tasks', '/data-tasks'],
  ['account-deletion', '/data-tasks?tab=account'],
  ['security', '/security'],
  ['ai-services', '/ai-services'],
  ['storage', '/storage'],
  ['system-health', '/system-health'],
  ['audit', '/audit'],
  ['settings', '/settings'],
  ['admins', '/admins'],
  ['empty', '/review/empty'],
  ['loading', '/review/loading'],
  ['error', '/review/error'],
  ['permission', '/review/permission'],
  ['danger-confirm', '/review/danger'],
] as const

test.beforeEach(async ({ page }) => {
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.hostname === '127.0.0.1') await route.continue()
    else await route.abort()
  })
})

for (const [name, path] of screens) {
  test('@flagship ' + name, async ({ page }, testInfo) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).toBeVisible()
    await mkdir('visual-artifacts', { recursive: true })
    await page.screenshot({
      path: join('visual-artifacts', testInfo.project.name + '-' + name + '.png'),
      fullPage: true,
      animations: 'disabled',
    })
    await expect(page).toHaveScreenshot(name + '.png', { fullPage: true })
  })
}
