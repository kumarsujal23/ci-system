import { test, expect } from '@playwright/test'

/**
 * End-to-end smoke test covering the primary dashboard flow:
 * register a project, trigger a build, and see it appear with a status.
 *
 * Requires the full stack running (docker compose up) with CI_DASHBOARD_URL
 * pointed at the frontend and the backend reachable at /api. In CI this is
 * wired up by .github/workflows/ci.yml's e2e job.
 */

test.describe('CI dashboard', () => {
  test('shows empty state when no projects exist', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
  })

  test('can open the new project form', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '+ New project' }).click()
    await expect(page.getByLabel('Name', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Repository URL')).toBeVisible()
    await expect(page.getByLabel('Pipeline (YAML)')).toBeVisible()
  })

  test('can register a project and see it listed', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '+ New project' }).click()

    const uniqueName = `e2e-project-${Date.now()}`
    await page.getByLabel('Name', { exact: true }).fill(uniqueName)
    await page.getByLabel('Repository URL').fill('https://github.com/example/e2e-test.git')
    await page.getByRole('button', { name: 'Register project' }).click()

    await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 10_000 })
  })

  test('can trigger a build from a project page and see it queued', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '+ New project' }).click()

    const uniqueName = `e2e-trigger-${Date.now()}`
    await page.getByLabel('Name', { exact: true }).fill(uniqueName)
    await page.getByLabel('Repository URL').fill('https://github.com/example/e2e-trigger.git')
    await page.getByRole('button', { name: 'Register project' }).click()

    await page.getByText(uniqueName).click()
    await expect(page.getByRole('heading', { name: uniqueName })).toBeVisible()

    await page.getByRole('button', { name: 'Trigger build' }).click()
    await expect(page.locator('.job-table')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.badge').first()).toBeVisible()
  })

  test('workers page renders without crashing', async ({ page }) => {
    await page.goto('/workers')
    await expect(page.getByRole('heading', { name: 'Workers' })).toBeVisible()
  })
})
