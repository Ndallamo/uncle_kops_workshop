import { expect, test } from '@playwright/test'

const password = process.env.QA_ACCEPTANCE_PASSWORD

if (!password) {
  throw new Error('Set QA_ACCEPTANCE_PASSWORD to run the isolated browser acceptance tests.')
}

const users = [
  {
    username: process.env.QA_ADMIN_USERNAME || 'qa_acceptance_admin',
    dashboard: 'Admin Dashboard',
  },
  {
    username: process.env.QA_MECHANIC_USERNAME || 'qa_acceptance_mechanic',
    dashboard: 'Mechanic Dashboard',
  },
  {
    username: process.env.QA_CUSTOMER_USERNAME || 'qa_acceptance_customer',
    dashboard: 'Customer Dashboard',
  },
]

async function signIn(page, username) {
  await page.goto('/login/')
  await page.getByLabel('Email or username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: /Sign In/ }).click()
}

test.describe('role dashboards', () => {
  for (const user of users) {
    test(`${user.username} can sign in to the correct dashboard`, async ({ page }) => {
      await signIn(page, user.username)

      await expect(page).toHaveURL(/\/$/)
      await expect(page).toHaveTitle(new RegExp(user.dashboard))
      await expect(page.locator('body')).toContainText(user.dashboard)
    })
  }
})

test('admin can open the primary workshop pages', async ({ page }) => {
  await signIn(page, users[0].username)
  await expect(page).toHaveTitle(/Admin Dashboard/)

  for (const path of [
    '/customers/',
    '/vehicles/',
    '/repairs/',
    '/invoices/',
    '/appointments/',
    '/parts/',
    '/services/',
    '/report/',
    '/audit-log/',
  ]) {
    const response = await page.goto(path)
    expect(response?.status(), `${path} should load`).toBe(200)
    await expect(page).toHaveURL(new RegExp(`${path.replaceAll('/', '\\/')}$`))
  }
})

test('mechanic is denied access to admin-only creation pages', async ({ page }) => {
  await signIn(page, users[1].username)
  await expect(page).toHaveTitle(/Mechanic Dashboard/)

  for (const path of ['/customers/new/', '/invoices/new/']) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/$/)
    await expect(page.locator('body')).toContainText('Access denied')
  }
})

test('admin can register a customer, vehicle, and repair order', async ({ page }) => {
  await signIn(page, users[0].username)
  await expect(page).toHaveTitle(/Admin Dashboard/)

  const runId = `${Date.now()}-${process.pid}`
  const customerName = `E2E Customer ${runId}`
  const email = `e2e-${runId}@example.test`
  const make = 'Toyota'
  const model = `QA-${runId}`
  const year = '2020'
  const description = `E2E brake inspection ${runId}`

  await page.goto('/customers/new/')
  await page.locator('input[name="first_name"]').fill('E2E')
  await page.locator('input[name="last_name"]').fill(`Customer ${runId}`)
  await page.locator('input[name="email"]').fill(email)
  await page.locator('input[name="phone"]').fill('071 000 0000')
  await page.locator('textarea[name="address"]').fill('QA Test Address, Bloemfontein')
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page).toHaveURL(/\/customers\/\d+\/$/)
  await expect(page.locator('body')).toContainText(customerName)
  await expect(page.locator('body')).toContainText(email)

  await page.getByRole('link', { name: 'Add vehicle', exact: true }).click()
  await page.locator('input[name="make"]').fill(make)
  await page.locator('input[name="model"]').fill(model)
  await page.locator('input[name="year"]').fill(year)
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page).toHaveURL(/\/vehicles\/\d+\/$/)
  await expect(page.locator('body')).toContainText(`${year} ${make} ${model}`)
  await expect(page.locator('body')).toContainText(customerName)

  await page.goto('/repairs/new/')
  const vehicleOption = page
    .locator('select[name="vehicle"] option')
    .filter({ hasText: `${year} ${make} ${model}` })
    .first()
  const vehicleId = await vehicleOption.getAttribute('value')
  if (!vehicleId) {
    throw new Error('The newly created vehicle was not available for a repair order.')
  }
  await page.locator('select[name="vehicle"]').selectOption(vehicleId)
  await page.locator('textarea[name="description"]').fill(description)
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page).toHaveURL(/\/repairs\/\d+\/$/)
  await expect(page.locator('body')).toContainText('Repair Details')
  await expect(page.locator('body')).toContainText(customerName)
  await expect(page.locator('body')).toContainText(`${year} ${make} ${model}`)
  await expect(page.locator('body')).toContainText(description)
})
