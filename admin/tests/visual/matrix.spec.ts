import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'

test('@matrix dashboard responsive matrix', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await mkdir('visual-artifacts', { recursive: true })
  await page.screenshot({
    path: join('visual-artifacts', testInfo.project.name + '-dashboard-matrix.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await expect(page).toHaveScreenshot('dashboard-matrix.png', { fullPage: true })
})
