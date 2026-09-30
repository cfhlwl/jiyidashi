import { expect, test } from '@playwright/test'

test('@flagship intentional dashboard mismatch', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.addStyleTag({ content: 'body { transform: translateX(3px) !important; }' })
  await expect(page).toHaveScreenshot('dashboard-matrix.png', { fullPage: true })
})
