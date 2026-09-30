import { expect, test } from '@playwright/test'

test('@flagship primary controls have accessible names', async ({ page }) => {
  await page.goto('/users')
  const buttons = page.getByRole('button')
  const count = await buttons.count()
  expect(count).toBeGreaterThan(0)
  for (let index = 0; index < count; index += 1) {
    const name = await buttons.nth(index).getAttribute('aria-label')
    const text = (await buttons.nth(index).innerText()).trim()
    expect(Boolean(name?.trim() || text)).toBeTruthy()
  }
})

test('@flagship danger dialog traps focus inside modal', async ({ page }) => {
  await page.goto('/review/danger')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const input = dialog.getByRole('textbox')
  await input.focus()
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press('Tab')
    const inside = await page.evaluate(() => {
      const active = document.activeElement
      const modal = document.querySelector('.ant-modal')
      return Boolean(active && modal && modal.contains(active))
    })
    expect(inside).toBeTruthy()
  }
})

test('@flagship 125 percent zoom keeps primary actions discoverable', async ({ page }) => {
  await page.goto('/admins')
  await page.evaluate(() => {
    document.documentElement.style.zoom = '1.25'
  })
  await expect(page.getByRole('button', { name: '创建管理员' })).toBeVisible()
})
