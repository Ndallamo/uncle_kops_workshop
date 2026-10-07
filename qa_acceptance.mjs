export default async function run(page) {
  const password = process.env.QA_ACCEPTANCE_PASSWORD
  if (!password) {
    throw new Error('Set QA_ACCEPTANCE_PASSWORD to run the isolated browser acceptance checks.')
  }

  const users = [
    { username: 'qa_acceptance_admin', expected: 'Admin Dashboard' },
    { username: 'qa_acceptance_mechanic', expected: 'Mechanic Dashboard' },
    { username: 'qa_acceptance_customer', expected: 'Customer Dashboard' },
  ]
  const results = []
  for (const user of users) {
    await page.goto('http://127.0.0.1:8000/login/')
    await page.getByLabel('Username').fill(user.username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: /Sign In/ }).click()
    await page.waitForLoadState('domcontentloaded')
    const body = await page.locator('body').innerText()
    results.push({ user: user.username, path: new URL(page.url()).pathname, title: await page.title(), expectedVisible: body.includes(user.expected) })
  }
  return results
}
