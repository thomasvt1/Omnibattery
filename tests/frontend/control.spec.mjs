import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const kp = page => page.getByRole('slider', { name: 'Proportional gain (Kp)' });
test.beforeEach(async ({page}) => {
  await page.route('https://fonts.googleapis.com/**',route=>route.abort());
  await page.goto('/tests/frontend/control-harness.html');
  await page.waitForFunction(()=>window.ready);
  await page.getByRole('button',{name:'Control',exact:true}).click();
  await expect(kp(page)).toHaveValue('0.35');
});

test('keyboard slider rejection restores HA state and actionable feedback',async({page})=>{
  await page.evaluate(()=>window.serviceMode='reject');
  await kp(page).focus(); await kp(page).press('ArrowRight');
  await expect(page.locator('.command-feedback')).toContainText('Permission denied');
  await expect(kp(page)).toHaveValue('0.35'); await expect(kp(page)).toBeEnabled();
  expect(await page.evaluate(()=>window.calls)).toEqual([{domain:'number',service:'set_value',data:{entity_id:'number.kp',value:.4}}]);
});

test('pending commands block duplicates and acceptance does not claim delivery',async({page})=>{
  await page.evaluate(()=>window.serviceMode='pending');
  await kp(page).press('ArrowRight'); await expect(kp(page)).toBeDisabled();
  await expect(kp(page)).toHaveAttribute('aria-busy','true');
  await kp(page).dispatchEvent('change');
  expect(await page.evaluate(()=>window.calls.length)).toBe(1);
  await page.evaluate(()=>window.finish('number.kp'));
  await expect(kp(page)).toBeEnabled();
  await expect(page.locator('.command-feedback')).toContainText('Setting accepted. Check live power');
});

test('independent success does not erase another command failure',async({page})=>{
  await page.evaluate(()=>window.serviceMode='pending');
  await kp(page).press('ArrowRight');
  await page.getByRole('switch',{name:'Manual mode',exact:true}).click();
  await page.evaluate(()=>window.finish('number.kp',true));
  await page.evaluate(()=>window.finish('switch.manual'));
  await expect(page.locator('.command-feedback')).toContainText('Permission denied');
});

test('switch semantics follow HA and unavailable controls cannot write',async({page})=>{
  const manual=page.getByRole('switch',{name:'Manual mode',exact:true});
  await expect(manual).toHaveAttribute('aria-checked','false');
  await page.evaluate(()=>window.setState('switch.manual','on'));
  await expect(manual).toHaveAttribute('aria-checked','true');
  await page.evaluate(()=>window.setState('number.kp','unavailable'));
  await expect(kp(page)).toHaveCount(0);
  expect(await page.evaluate(()=>window.calls.length)).toBe(0);
});

test('row and section help work by keyboard and dismiss with Escape',async({page})=>{
  const row=page.getByRole('button',{name:'Proportional gain (Kp)',exact:true});
  await row.focus(); await row.press('Enter');
  await expect(page.locator('.info-pop')).toBeVisible();
  await row.press('Escape'); await expect(page.locator('.info-pop')).toBeHidden();
  const info=page.locator('.card[data-tk="secPd"] .card-info');
  await info.focus(); await info.press('Space'); await expect(page.locator('.info-pop')).toBeVisible();
  await info.press('Escape'); await expect(page.locator('.info-pop')).toBeHidden();
  await expect(info).toBeFocused();
});

test('mobile controls fit viewport and pass accessibility checks',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
});
